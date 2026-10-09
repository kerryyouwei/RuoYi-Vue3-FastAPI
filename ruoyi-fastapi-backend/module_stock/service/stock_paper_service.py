"""模拟交易（paper）服务：账户初始化、持仓/信号/成交/净值查询与每日信号/撮合。"""

import asyncio
import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.database import DataSourceRegistry
from exceptions.exception import ServiceException
from module_stock.dao.stock_paper_dao import StockPaperDao
from module_stock.dao.stock_scan_dao import StockScanDao
from module_stock.entity.do.stock_paper_do import (
    StockPaperAccount,
    StockPaperDailySnapshot,
    StockPaperOrder,
    StockPaperPosition,
    StockPaperSignal,
    StockPaperUniverse,
)
from module_stock.entity.vo.stock_paper_vo import (
    PaperAccountInitRequestModel,
    PaperAccountModel,
    PaperPositionModel,
    PaperSnapshotModel,
    PaperUniverseModel,
)
from module_stock.service.stock_signal_service import StockSignalService
from module_stock.service.stock_strategy_service import StockStrategyService
from utils.log_util import logger
from utils.page_util import PageModel
from utils.time_util import TimezoneUtil

COMMISSION_RATE = 0.0003
TRADING_DAY_WEEKDAY = 5  # weekday() < 5 means Mon-Fri
STAMP_TAX_RATE = 0.001
MIN_COMMISSION = 5.0
DEFAULT_ACCOUNT_NAME = 'default'
LOT_SIZE = 100


def _to_float(value: Any) -> float | None:
    """将任意值安全转换为有限浮点数。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class StockPaperService:
    """模拟盘账户、标的池、持仓、信号、撮合与净值快照。"""

    _TENCENT_FIELD_MIN = 6

    # ---------------------------------------------------------------- 行情取价
    @staticmethod
    def _tencent_symbol(code: str) -> str:
        """将6位A股代码转换为腾讯行情前缀代码。"""
        if code.startswith(('5', '6', '9')):
            return f'sh{code}'
        if code.startswith(('0', '1', '2', '3')):
            return f'sz{code}'
        if code.startswith(('4', '8')):
            return f'bj{code}'
        return f'sh{code}'

    @staticmethod
    def _latest_price_from_realtime(code: str, on_date: str | None = None) -> float | None:
        """优先读取 QUANTAXIS stock_realtime 已采集的最新价。"""
        try:
            import QUANTAXIS as QA  # noqa: PLC0415
        except Exception:
            return None
        try:
            collection = QA.DATABASE.stock_realtime
            query: dict[str, Any] = {'code': code}
            if on_date:
                query['date'] = {'$lte': on_date}
            cursor = collection.find(query, {'_id': 0, 'price': 1, 'date': 1}).sort('date', -1).limit(1)
            documents = list(cursor)
            if documents:
                return _to_float(documents[0].get('price'))
        except Exception as exc:
            logger.bind(code=code).warning(f'股票{code}读取stock_realtime最新价失败：{exc}')
        return None

    @staticmethod
    def _latest_daily_close(code: str, end_date: str) -> float | None:
        """退化方案：读取 QUANTAXIS 最新日线收盘价。"""
        try:
            import QUANTAXIS as QA  # noqa: PLC0415
        except Exception:
            return None
        try:
            data = QA.QA_fetch_stock_day_adv(code, '2000-01-01', end_date)
            if data is None or data.data.empty:
                return None
            return _to_float(data.data.iloc[-1]['close'])
        except Exception as exc:
            logger.bind(code=code).warning(f'股票{code}读取QA日线最新收盘价失败：{exc}')
        return None

    @staticmethod
    def _open_from_qa(code: str) -> float | None:
        """优先读取 QUANTAXIS tdx 实时行情的开盘价。"""
        try:
            import QUANTAXIS as QA  # noqa: PLC0415
        except Exception:
            return None
        try:
            frame = QA.QA_fetch_get_stock_realtime(package='tdx', code=[code])
            if frame is None or frame.empty:
                return None
            row = frame.reset_index().iloc[0].to_dict()
            open_price = _to_float(row.get('open')) or _to_float(row.get('open_price'))
            if open_price is not None:
                return open_price
            return _to_float(row.get('price'))
        except Exception as exc:
            logger.bind(code=code).warning(f'股票{code}读取QA实时开盘价失败：{exc}')
        return None

    @staticmethod
    def _price_from_tencent(code: str) -> float | None:
        """兜底读取腾讯实时行情（开盘价优先，当前价兜底）。"""
        symbol = StockPaperService._tencent_symbol(code)
        try:
            import requests  # noqa: PLC0415

            response = requests.get(f'https://qt.gtimg.cn/q={symbol}', timeout=5)
            response.encoding = 'gbk'
            text = response.text
            if '="' not in text:
                return None
            payload = text.split('="', 1)[1].rsplit('"', 1)[0]
            fields = payload.split('~')
            if len(fields) < StockPaperService._TENCENT_FIELD_MIN:
                return None
            open_price = _to_float(fields[5])
            if open_price is not None and open_price > 0:
                return open_price
            return _to_float(fields[3])
        except Exception as exc:
            logger.bind(code=code).warning(f'股票{code}读取腾讯行情失败：{exc}')
        return None

    @staticmethod
    def _fetch_close(code: str, end_date: str) -> float | None:
        """收盘价：优先已采集实时快照，退化QA最新日线。"""
        price = StockPaperService._latest_price_from_realtime(code, end_date)
        if price is not None and price > 0:
            return price
        return StockPaperService._latest_daily_close(code, end_date)

    @staticmethod
    def _fetch_open(code: str) -> float | None:
        """开盘价：优先QA tdx实时，腾讯兜底。"""
        price = StockPaperService._open_from_qa(code)
        if price is not None and price > 0:
            return price
        return StockPaperService._price_from_tencent(code)

    # ---------------------------------------------------------------- 日期工具
    @staticmethod
    def _today() -> str:
        return datetime.now(TimezoneUtil.get_app_timezone()).date().isoformat()

    @staticmethod
    def _is_trading_day(value: str) -> bool:
        day = date.fromisoformat(value)
        return day.weekday() < TRADING_DAY_WEEKDAY  # 周一至周五视为交易日，节假日由“能取到行情”兜底

    @staticmethod
    def _next_trading_day(value: str) -> str:
        day = date.fromisoformat(value)
        while True:
            day += timedelta(days=1)
            if day.weekday() < TRADING_DAY_WEEKDAY:
                return day.isoformat()

    # ---------------------------------------------------------------- 聚合口径
    @staticmethod
    def _account_equity(account: StockPaperAccount, positions: list[StockPaperPosition]) -> dict[str, float]:
        position_value = sum((float(p.quantity) * float(p.last_price or 0)) for p in positions)
        total_equity = float(account.cash) + position_value
        pnl = total_equity - float(account.initial_cash)
        return {
            'cash': float(account.cash),
            'position_value': position_value,
            'total_equity': total_equity,
            'pnl': pnl,
            'return_rate': pnl / float(account.initial_cash) if account.initial_cash else 0.0,
        }

    @classmethod
    async def _require_account(cls, db: AsyncSession, account_name: str) -> StockPaperAccount:
        account = await StockPaperDao.get_account(db, account_name)
        if account is None:
            raise ServiceException(message='模拟账户尚未初始化，请先初始化账户')
        return account

    # ---------------------------------------------------------------- 初始化
    @classmethod
    async def init_account(cls, db: AsyncSession, request: PaperAccountInitRequestModel) -> dict[str, Any]:
        StockStrategyService._file(request.strategy_name)
        existing = await StockPaperDao.get_account(db, request.account_name)
        account = existing or StockPaperAccount(account_name=request.account_name)
        account.strategy_name = request.strategy_name
        account.initial_cash = request.initial_cash
        account.cash = float(request.initial_cash)
        account.status = 'active'
        if existing is None:
            await StockPaperDao.create_account(db, account)
        else:
            await StockPaperDao.update_account(
                db,
                account.id,
                strategy_name=account.strategy_name,
                initial_cash=account.initial_cash,
                cash=account.cash,
                status=account.status,
            )

        # 清空历史交易/信号/持仓/快照。
        await StockPaperDao.delete_positions_by_account(db, account.id)
        await StockPaperDao.delete_orders_by_account(db, account.id)
        await StockPaperDao.delete_signals_by_account(db, account.id)
        await StockPaperDao.delete_snapshots_by_account(db, account.id)

        added_count = 0
        skipped_count = 0
        seen: set[str] = set()
        if request.codes:
            for code in request.codes:
                if code in seen:
                    skipped_count += 1
                    continue
                seen.add(code)
                universe = await StockPaperDao.get_universe_by_code(db, account.id, code)
                if universe is not None:
                    await StockPaperDao.update_universe_by_code(
                        db, account.id, code, source_batch_id=request.source_batch_id, status='active'
                    )
                    skipped_count += 1
                    continue
                await StockPaperDao.add_universe(
                    db,
                    StockPaperUniverse(account_id=account.id, code=code, source_batch_id=request.source_batch_id, status='active'),
                )
                added_count += 1
            # 非本次 codes 中但仍在标的池的记录，一律停用。
            await StockPaperDao.deactivate_universe_except(db, account.id, seen)
        # codes 为空时保留现有标的池不变，仅重置资金与交易记录。
        await db.commit()
        logger.bind(account_name=request.account_name, added_count=added_count, skipped_count=skipped_count).info('模拟账户初始化完成')
        return {'accountId': account.id, 'accountName': account.account_name, 'addedCount': added_count, 'skippedCount': skipped_count}

    # ---------------------------------------------------------------- 查询
    @classmethod
    async def get_account(cls, db: AsyncSession, account_name: str = DEFAULT_ACCOUNT_NAME) -> PaperAccountModel:
        account = await cls._require_account(db, account_name)
        positions = await StockPaperDao.list_positions(db, account.id)
        equity = cls._account_equity(account, positions)
        return PaperAccountModel(
            id=account.id,
            account_name=account.account_name,
            strategy_name=account.strategy_name,
            initial_cash=account.initial_cash,
            cash=equity['cash'],
            total_equity=equity['total_equity'],
            position_value=equity['position_value'],
            return_rate=equity['return_rate'],
            pnl=equity['pnl'],
            status=account.status,
        )

    @classmethod
    async def list_positions(cls, db: AsyncSession, account_name: str = DEFAULT_ACCOUNT_NAME) -> list[PaperPositionModel]:
        account = await cls._require_account(db, account_name)
        positions = await StockPaperDao.list_positions(db, account.id)
        result: list[PaperPositionModel] = []
        for position in positions:
            price = position.last_price or 0.0
            market_value = float(position.quantity) * float(price)
            cost = float(position.avg_cost) * float(position.quantity)
            result.append(
                PaperPositionModel(
                    id=position.id,
                    account_id=position.account_id,
                    code=position.code,
                    name=position.name,
                    quantity=position.quantity,
                    available_quantity=position.available_quantity,
                    avg_cost=position.avg_cost,
                    last_price=position.last_price,
                    market_value=market_value,
                    pnl=market_value - cost,
                )
            )
        return result

    @classmethod
    async def list_universe(cls, db: AsyncSession, account_name: str = DEFAULT_ACCOUNT_NAME) -> list[PaperUniverseModel]:
        """返回模拟盘当前标的池（含来源批次与状态）。"""
        account = await cls._require_account(db, account_name)
        items = await StockPaperDao.get_universe(db, account.id)
        return [PaperUniverseModel.model_validate(item) for item in items]

    @classmethod
    async def list_signals(cls, db: AsyncSession, account_name: str, page_num: int, page_size: int) -> PageModel:
        account = await cls._require_account(db, account_name)
        return await StockPaperDao.list_signals(db, account.id, page_num, page_size)

    @classmethod
    async def list_orders(cls, db: AsyncSession, account_name: str, page_num: int, page_size: int) -> PageModel:
        account = await cls._require_account(db, account_name)
        return await StockPaperDao.list_orders(db, account.id, page_num, page_size)

    @classmethod
    async def list_snapshot(cls, db: AsyncSession, account_name: str, start_date: str | None = None, end_date: str | None = None) -> list[PaperSnapshotModel]:
        account = await cls._require_account(db, account_name)
        snapshots = await StockPaperDao.list_snapshots(db, account.id, start_date, end_date)
        return [PaperSnapshotModel.model_validate(item) for item in snapshots]

    # ---------------------------------------------------------------- 收盘信号
    @classmethod
    async def run_eod_signal(cls) -> None:
        today = cls._today()
        if not cls._is_trading_day(today):
            logger.bind(today=today).info('非交易日，跳过模拟盘收盘信号计算')
            return
        async with DataSourceRegistry.session(log_sql=False) as db:
            account = await StockPaperDao.get_account(db, DEFAULT_ACCOUNT_NAME)
            if account is None or account.status != 'active':
                logger.bind(today=today).info('模拟账户未初始化或非激活，跳过收盘信号')
                return
            universe = await StockPaperDao.get_universe(db, account.id)
            if not universe:
                logger.bind(today=today).info('模拟盘标的池为空，跳过收盘信号')
                return
            if not account.strategy_name:
                logger.bind(today=today).warning('模拟账户未配置策略，跳过收盘信号')
                return

            execute_date = cls._next_trading_day(today)
            position_by_code = {p.code: p for p in await StockPaperDao.list_positions(db, account.id)}
            for item in universe:
                close = await asyncio.to_thread(cls._fetch_close, item.code, today)
                position = position_by_code.get(item.code)
                if close is None or close <= 0:
                    logger.bind(code=item.code, today=today).warning('未获取到收盘价，跳过该标的信号计算')
                    continue
                if position is not None:
                    await StockPaperDao.update_position(db, position.id, last_price=close)
                signal = await asyncio.to_thread(
                    StockSignalService.compute_signal,
                    account.strategy_name,
                    item.code,
                    {},
                    today,
                    close,
                )
                await cls._upsert_signal(
                    db, account.id, item.code, today, execute_date, signal['signal'], signal['reason'], close
                )

            await cls._upsert_snapshot(db, account)
            await db.commit()
        logger.bind(today=today, execute_date=execute_date, count=len(universe)).info('模拟盘收盘信号计算完成')

    @staticmethod
    async def _upsert_signal(
        db: AsyncSession,
        account_id: int,
        code: str,
        signal_date: str,
        execute_date: str,
        signal: str,
        reason: str,
        close_price: float | None,
    ) -> None:
        existing = await StockPaperDao.get_signal(db, account_id, code, signal_date)
        if existing is None:
            await StockPaperDao.create_signal(
                db,
                StockPaperSignal(
                    account_id=account_id,
                    code=code,
                    signal_date=signal_date,
                    signal=signal,
                    reason=reason,
                    close_price=close_price,
                    execute_date=execute_date,
                    status='pending',
                ),
            )
            return
        await StockPaperDao.update_signal(
            db, existing.id, signal=signal, reason=reason, close_price=close_price, execute_date=execute_date, status='pending'
        )

    @classmethod
    async def _upsert_snapshot(cls, db: AsyncSession, account: StockPaperAccount) -> None:
        positions = await StockPaperDao.list_positions(db, account.id)
        equity = cls._account_equity(account, positions)
        today = cls._today()
        snapshot = await StockPaperDao.get_snapshot(db, account.id, today)
        values = {
            'total_equity': equity['total_equity'],
            'cash': equity['cash'],
            'position_value': equity['position_value'],
            'pnl': equity['pnl'],
            'return_rate': equity['return_rate'],
        }
        if snapshot is None:
            await StockPaperDao.create_snapshot(db, StockPaperDailySnapshot(account_id=account.id, date=today, **values))
        else:
            await StockPaperDao.update_snapshot(db, snapshot.id, **values)

    # ---------------------------------------------------------------- 开盘撮合
    @classmethod
    async def run_morning_execute(cls) -> None:
        today = cls._today()
        if not cls._is_trading_day(today):
            logger.bind(today=today).info('非交易日，跳过模拟盘开盘撮合')
            return
        async with DataSourceRegistry.session(log_sql=False) as db:
            account = await StockPaperDao.get_account(db, DEFAULT_ACCOUNT_NAME)
            if account is None or account.status != 'active':
                logger.bind(today=today).info('模拟账户未初始化或非激活，跳过开盘撮合')
                return
            await StockPaperDao.settle_positions(db, account.id)

            signals = await StockPaperDao.pending_signals_by_execute_date(db, account.id, today)
            positions = {p.code: p for p in await StockPaperDao.list_positions(db, account.id)}
            universe = await StockPaperDao.get_universe(db, account.id)
            universe_names = {item.code: item.name for item in universe}
            active_count = max(len(universe), 1)
            equity = cls._account_equity(account, list(positions.values()))
            total_equity = equity['total_equity']

            for signal in signals:
                price = await asyncio.to_thread(cls._fetch_open, signal.code)
                name = universe_names.get(signal.code)
                if signal.signal == '持有':
                    await StockPaperDao.update_signal(db, signal.id, status='executed')
                    continue
                if signal.signal == '买入':
                    await cls._execute_buy(db, account, signal, name, positions, total_equity, active_count, price)
                elif signal.signal == '卖出':
                    await cls._execute_sell(db, account, signal, name, positions, price)
                else:
                    await StockPaperDao.update_signal(db, signal.id, status='skipped')
                await db.flush()
            await db.commit()
        logger.bind(today=today, execute_count=len(signals)).info('模拟盘开盘撮合完成')

    @classmethod
    async def _execute_buy(
        cls,
        db: AsyncSession,
        account: StockPaperAccount,
        signal: StockPaperSignal,
        name: str | None,
        positions: dict[str, StockPaperPosition],
        total_equity: float,
        active_count: int,
        price: float | None,
    ) -> None:
        skip = cls._price_skip_reason(price)
        if skip:
            await cls._mark_skipped(db, account.id, signal, name, price, skip)
            return
        assert price is not None
        if signal.code in positions and positions[signal.code].quantity > 0:
            await cls._mark_skipped(db, account.id, signal, name, price, '已有持仓，不再加仓')
            return
        target = total_equity / active_count
        quantity = int(target / float(price) // LOT_SIZE * LOT_SIZE)
        amount = float(quantity) * float(price)
        commission = max(amount * COMMISSION_RATE, MIN_COMMISSION) if quantity > 0 else 0.0
        total_cost = amount + commission
        if quantity <= 0 or float(account.cash) < total_cost:
            await cls._mark_skipped(
                db, account.id, signal, name, price, f'资金不足：所需{total_cost:.2f}，可用现金{account.cash:.2f}'
            )
            return

        await StockPaperDao.update_account(db, account.id, cash=float(account.cash) - total_cost)
        position = positions.get(signal.code)
        if position is None:
            await StockPaperDao.create_position(
                db,
                StockPaperPosition(
                    account_id=account.id,
                    code=signal.code,
                    name=name,
                    quantity=quantity,
                    available_quantity=0,
                    avg_cost=float(price),
                    last_price=float(price),
                ),
            )
        else:
            new_quantity = position.quantity + quantity
            new_cost = (float(position.avg_cost) * position.quantity + amount) / new_quantity
            await StockPaperDao.update_position(db, position.id, quantity=new_quantity, avg_cost=new_cost, last_price=float(price))
            position.quantity = new_quantity
            position.avg_cost = new_cost
            position.last_price = float(price)

        await StockPaperDao.create_order(
            db,
            StockPaperOrder(
                account_id=account.id,
                code=signal.code,
                name=name,
                signal_date=signal.signal_date,
                execute_date=signal.execute_date or cls._today(),
                side='买入',
                price=float(price),
                quantity=quantity,
                amount=amount,
                commission=commission,
                stamp_tax=0.0,
                execute_status='成交',
            ),
        )
        await StockPaperDao.update_signal(db, signal.id, status='executed')

    @classmethod
    async def _execute_sell(
        cls,
        db: AsyncSession,
        account: StockPaperAccount,
        signal: StockPaperSignal,
        name: str | None,
        positions: dict[str, StockPaperPosition],
        price: float | None,
    ) -> None:
        skip = cls._price_skip_reason(price)
        if skip:
            await cls._mark_skipped(db, account.id, signal, name, price, skip)
            return
        assert price is not None
        position = positions.get(signal.code)
        if position is None or position.available_quantity <= 0:
            await cls._mark_skipped(db, account.id, signal, name, price, '无可用持仓可卖（T+1）')
            return

        quantity = int(position.available_quantity)
        amount = float(quantity) * float(price)
        commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
        stamp_tax = amount * STAMP_TAX_RATE
        await StockPaperDao.update_account(db, account.id, cash=float(account.cash) + amount - commission - stamp_tax)
        if position.quantity == quantity:
            await StockPaperDao.delete_positions_by_code(db, account.id, signal.code)
            positions.pop(signal.code, None)
        else:
            await StockPaperDao.update_position(
                db, position.id, quantity=position.quantity - quantity, available_quantity=position.available_quantity - quantity
            )
            position.quantity -= quantity
            position.available_quantity -= quantity

        await StockPaperDao.create_order(
            db,
            StockPaperOrder(
                account_id=account.id,
                code=signal.code,
                name=name,
                signal_date=signal.signal_date,
                execute_date=signal.execute_date or cls._today(),
                side='卖出',
                price=float(price),
                quantity=quantity,
                amount=amount,
                commission=commission,
                stamp_tax=stamp_tax,
                execute_status='成交',
            ),
        )
        await StockPaperDao.update_signal(db, signal.id, status='executed')

    @staticmethod
    def _price_skip_reason(price: float | None) -> str | None:
        if price is None or price <= 0:
            return '无有效成交价（停牌或行情缺失）'
        return None

    @classmethod
    async def _mark_skipped(
        cls,
        db: AsyncSession,
        account_id: int,
        signal: StockPaperSignal,
        name: str | None,
        price: float | None,
        reason: str,
    ) -> None:
        side = signal.signal if signal.signal in {'买入', '卖出'} else '买入'
        await StockPaperDao.create_order(
            db,
            StockPaperOrder(
                account_id=account_id,
                code=signal.code,
                name=name,
                signal_date=signal.signal_date,
                execute_date=signal.execute_date or cls._today(),
                side=side,
                price=price,
                quantity=0,
                amount=0.0,
                commission=0.0,
                stamp_tax=0.0,
                execute_status='跳过',
                skip_reason=reason,
            ),
        )
        await StockPaperDao.update_signal(db, signal.id, status='skipped')

    # ---------------------------------------------------------------- 勾选入池
    @classmethod
    async def ensure_account(cls, db: AsyncSession, strategy_name: str | None = None, initial_cash: int = 1_000_000) -> StockPaperAccount:
        """确保系统级默认账户存在，缺少时按回测批次参数兜底创建。"""
        account = await StockPaperDao.get_account(db, DEFAULT_ACCOUNT_NAME)
        if account is not None:
            return account
        account = StockPaperAccount(
            account_name=DEFAULT_ACCOUNT_NAME,
            strategy_name=strategy_name,
            initial_cash=initial_cash,
            cash=float(initial_cash),
            status='active',
        )
        await StockPaperDao.create_account(db, account)
        return account

    @classmethod
    async def pick_to_universe(cls, db: AsyncSession, batch_id: str, codes: list[str]) -> dict[str, Any]:
        """批量回测结果的勾选标的写入模拟盘标的池，返回新增/跳过数量。"""
        if not codes:
            raise ServiceException(message='请至少勾选一只股票')
        batch = await StockScanDao.get_batch(db, batch_id)
        if batch is None:
            raise ServiceException(message='批量回测批次不存在')
        items = {item.code: item for item in await StockScanDao.get_items_for_codes(db, batch_id, codes)}
        account = await cls.ensure_account(db, batch.strategy_name, batch.initial_cash)

        added_count = 0
        skipped_count = 0
        for code in codes:
            universe = await StockPaperDao.get_universe_by_code(db, account.id, code)
            item = items.get(code)
            name = item.name if item is not None else (universe.name if universe is not None else None)
            if universe is not None and universe.status == 'active':
                skipped_count += 1
                continue
            if universe is None:
                await StockPaperDao.add_universe(
                    db,
                    StockPaperUniverse(account_id=account.id, code=code, name=name, source_batch_id=batch_id, status='active'),
                )
            else:
                await StockPaperDao.update_universe_by_code(
                    db, account.id, code, name=name, source_batch_id=batch_id, status='active'
                )
            added_count += 1
        await db.commit()
        logger.bind(batch_id=batch_id, account_id=account.id, added_count=added_count, skipped_count=skipped_count).info('回测结果已勾选加入模拟盘标的池')
        return {'accountId': account.id, 'addedCount': added_count, 'skippedCount': skipped_count}
