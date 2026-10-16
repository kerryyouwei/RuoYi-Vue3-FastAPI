"""模拟交易（paper）服务：账户初始化、持仓/信号/成交/净值查询与每日信号/撮合。"""

import asyncio
import math
import time
from datetime import date, datetime, timedelta
from datetime import time as time_type
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.database import DataSourceRegistry
from config.env import FeishuNotifyConfig
from exceptions.exception import ServiceException
from module_stock.dao.stock_paper_dao import StockPaperDao
from module_stock.dao.stock_scan_dao import StockScanDao
from module_stock.entity.do.stock_paper_do import (
    StockFeishuMessage,
    StockPaperAccount,
    StockPaperDailySnapshot,
    StockPaperOrder,
    StockPaperPosition,
    StockPaperSignal,
    StockPaperUniverse,
)
from module_stock.entity.vo.stock_day_vo import StockDayImportModel
from module_stock.entity.vo.stock_paper_vo import (
    PaperAccountInitRequestModel,
    PaperAccountModel,
    PaperPositionModel,
    PaperRealtimeQuoteModel,
    PaperSnapshotModel,
    PaperUniverseModel,
)
from module_stock.service.stock_day_service import StockDayService
from module_stock.service.stock_feishu_notification_service import (
    FeishuNotificationService,
    FeishuSendResult,
    FeishuSignal,
)
from module_stock.service.stock_realtime_service import StockRealtimeService
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

_REALTIME_QUOTE_CACHE_TTL_SECONDS = 10.0
_REALTIME_QUOTE_CACHE_MAX_ENTRIES = 8
_realtime_quote_cache: dict[frozenset[str], tuple[float, dict[str, dict[str, Any]]]] = {}


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
        """优先读取 QUANTAXIS stock_realtime 当日已采集的最新价。"""
        try:
            import QUANTAXIS as QA  # noqa: PLC0415
        except Exception:
            return None
        try:
            collection = QA.DATABASE.stock_realtime
            query: dict[str, Any] = {'code': code}
            if on_date:
                query['date'] = {'$eq': on_date}
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
        """收盘价：优先当日实时快照，否则退化QA最新日线。"""
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
    def _now_hms() -> str:
        return datetime.now(TimezoneUtil.get_app_timezone()).strftime('%H:%M:%S')

    @staticmethod
    def _stock_names_from_mongo(codes: list[str]) -> dict[str, str]:
        """从 MongoDB stock_list 集合查询股票名称映射。"""
        try:
            import QUANTAXIS as QA  # noqa: PLC0415
        except ImportError:
            return {}
        try:
            docs = list(
                QA.DATABASE.stock_list.find({'code': {'$in': codes}}, {'_id': 0, 'code': 1, 'name': 1, 'code_name': 1})
            )
        except Exception:
            return {}
        result: dict[str, str] = {}
        for doc in docs:
            code = str(doc.get('code') or '').strip()
            name = str(doc.get('name') or doc.get('code_name') or '').strip()
            if code and name and name.lower() not in {'nan', 'none', ''}:
                result[code] = name
        return result

    @classmethod
    def _fill_page_names(cls, page: PageModel) -> None:
        """为分页结果中缺失名称的记录补充股票名称。"""
        if not page or not page.rows:
            return
        missing_codes: list[str] = []
        for row in page.rows:
            if isinstance(row, dict) and not row.get('name'):
                code = str(row.get('code') or '').strip()
                if code and code not in missing_codes:
                    missing_codes.append(code)
        if not missing_codes:
            return
        name_map = cls._stock_names_from_mongo(missing_codes)
        for row in page.rows:
            if isinstance(row, dict) and not row.get('name'):
                code = str(row.get('code') or '').strip()
                if code in name_map:
                    row['name'] = name_map[code]

    @staticmethod
    def _is_trading_day(value: str) -> bool:
        day = date.fromisoformat(value)
        return day.weekday() < TRADING_DAY_WEEKDAY  # 周一至周五视为交易日，节假日由“能取到行情”兜底

    @staticmethod
    def _is_trading_time(now: datetime | None = None) -> bool:
        """A股连续竞价交易时段：09:30-11:30、13:00-15:00。"""
        current = now or datetime.now(TimezoneUtil.get_app_timezone())
        current_time = current.time()
        return time_type(9, 30) <= current_time <= time_type(11, 30) or time_type(13, 0) <= current_time <= time_type(
            15, 0
        )

    @staticmethod
    def _next_trading_day(value: str) -> str:
        day = date.fromisoformat(value)
        while True:
            day += timedelta(days=1)
            if day.weekday() < TRADING_DAY_WEEKDAY:
                return day.isoformat()

    @classmethod
    async def _fetch_realtime_quotes_cached(cls, codes: list[str]) -> dict[str, dict[str, Any]]:
        """批量获取实时行情并做短时缓存，避免持仓/账户接口重复请求行情源。"""
        key = frozenset(codes)
        now = time.monotonic()
        cached = _realtime_quote_cache.get(key)
        if cached is not None and now - cached[0] < _REALTIME_QUOTE_CACHE_TTL_SECONDS:
            return cached[1]

        quotes_by_code = {q['code']: q for q in await StockRealtimeService.fetch_realtime(codes)}

        expired = [k for k, (ts, _) in _realtime_quote_cache.items() if now - ts >= _REALTIME_QUOTE_CACHE_TTL_SECONDS]
        for k in expired:
            _realtime_quote_cache.pop(k, None)
        if len(_realtime_quote_cache) >= _REALTIME_QUOTE_CACHE_MAX_ENTRIES:
            oldest = min(_realtime_quote_cache, key=lambda k: _realtime_quote_cache[k][0])
            _realtime_quote_cache.pop(oldest, None)
        _realtime_quote_cache[key] = (now, quotes_by_code)
        return quotes_by_code

    @classmethod
    async def _refresh_position_prices(cls, db: AsyncSession, positions: list[StockPaperPosition]) -> bool:
        """用实时行情刷新持仓最新价（内存与数据库），刷新失败时保留原缓存价。"""
        held = [p for p in positions if p.code and int(p.quantity or 0) > 0]
        if not held:
            return False
        quotes_by_code = await cls._fetch_realtime_quotes_cached([p.code for p in held])
        changed = False
        for position in held:
            quote = quotes_by_code.get(position.code)
            price = _to_float(quote['price']) if quote is not None else None
            if price is None or price <= 0:
                logger.bind(code=position.code).warning('持仓最新价实时行情无效，保留原缓存价')
                continue
            price = float(price)
            if position.last_price != price:
                position.last_price = price
                await StockPaperDao.update_position(db, position.id, last_price=price)
                changed = True
        if changed:
            await db.commit()
            # 兼容会话 expire_on_commit 为 True 的情况：commit 后不要继续访问已过期 ORM 字段。
            for position in positions:
                await db.refresh(position)
        return changed

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
            name_map = cls._stock_names_from_mongo(list(request.codes))
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
                    StockPaperUniverse(
                        account_id=account.id,
                        code=code,
                        name=name_map.get(code),
                        source_batch_id=request.source_batch_id,
                        status='active',
                    ),
                )
                added_count += 1
            # 非本次 codes 中但仍在标的池的记录，一律停用。
            await StockPaperDao.deactivate_universe_except(db, account.id, seen)
        # codes 为空时保留现有标的池不变，仅重置资金与交易记录。
        await db.commit()
        logger.bind(account_name=request.account_name, added_count=added_count, skipped_count=skipped_count).info(
            '模拟账户初始化完成'
        )
        return {
            'accountId': account.id,
            'accountName': account.account_name,
            'addedCount': added_count,
            'skippedCount': skipped_count,
        }

    # ---------------------------------------------------------------- 查询
    @classmethod
    async def get_account(cls, db: AsyncSession, account_name: str = DEFAULT_ACCOUNT_NAME) -> PaperAccountModel:
        account = await cls._require_account(db, account_name)
        positions = await StockPaperDao.list_positions(db, account.id)
        changed = await cls._refresh_position_prices(db, positions)
        if changed:
            await db.refresh(account)
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
    async def list_positions(
        cls, db: AsyncSession, account_name: str = DEFAULT_ACCOUNT_NAME
    ) -> list[PaperPositionModel]:
        account = await cls._require_account(db, account_name)
        positions = await StockPaperDao.list_positions(db, account.id)
        await cls._refresh_position_prices(db, positions)
        missing_pos = [p for p in positions if not p.name]
        if missing_pos:
            name_map = cls._stock_names_from_mongo([p.code for p in missing_pos])
            for p in missing_pos:
                name = name_map.get(p.code)
                if name:
                    await StockPaperDao.update_position(db, p.id, name=name)
                    p.name = name
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
    async def list_universe(
        cls, db: AsyncSession, account_name: str = DEFAULT_ACCOUNT_NAME
    ) -> list[PaperUniverseModel]:
        """返回模拟盘当前标的池（含来源批次与状态）。"""
        account = await cls._require_account(db, account_name)
        items = await StockPaperDao.get_universe(db, account.id)
        missing_uni = [i for i in items if not i.name]
        if missing_uni:
            name_map = cls._stock_names_from_mongo([i.code for i in missing_uni])
            for i in missing_uni:
                name = name_map.get(i.code)
                if name:
                    await StockPaperDao.update_universe_by_code(db, account.id, i.code, name=name)
                    i.name = name
        return [PaperUniverseModel.model_validate(item) for item in items]

    @classmethod
    async def list_signals(cls, db: AsyncSession, account_name: str, page_num: int, page_size: int) -> PageModel:
        account = await cls._require_account(db, account_name)
        page = await StockPaperDao.list_signals(db, account.id, page_num, page_size)
        cls._fill_page_names(page)
        return page

    @classmethod
    async def list_orders(cls, db: AsyncSession, account_name: str, page_num: int, page_size: int) -> PageModel:
        account = await cls._require_account(db, account_name)
        page = await StockPaperDao.list_orders(db, account.id, page_num, page_size)
        cls._fill_page_names(page)
        return page

    @classmethod
    async def list_snapshot(
        cls, db: AsyncSession, account_name: str, start_date: str | None = None, end_date: str | None = None
    ) -> list[PaperSnapshotModel]:
        account = await cls._require_account(db, account_name)
        snapshots = await StockPaperDao.list_snapshots(db, account.id, start_date, end_date)
        return [PaperSnapshotModel.model_validate(item) for item in snapshots]

    # ---------------------------------------------------------------- 标的池实时行情
    @classmethod
    async def get_realtime_quotes(
        cls, db: AsyncSession, account_name: str = DEFAULT_ACCOUNT_NAME
    ) -> list[PaperRealtimeQuoteModel]:
        """获取标的池每只股票的实时价格与持仓浮动盈亏。"""
        account = await cls._require_account(db, account_name)
        universe = await StockPaperDao.get_universe(db, account.id)
        if not universe:
            return []
        missing = [item for item in universe if not item.name]
        if missing:
            name_map = cls._stock_names_from_mongo([i.code for i in missing])
            for item in missing:
                name = name_map.get(item.code)
                if name:
                    await StockPaperDao.update_universe_by_code(db, account.id, item.code, name=name)
                    item.name = name
        positions = {p.code: p for p in await StockPaperDao.list_positions(db, account.id)}
        codes = [item.code for item in universe]
        quotes = await StockRealtimeService.fetch_realtime(codes)
        quotes_by_code = {q[chr(99) + chr(111) + chr(100) + chr(101)]: q for q in quotes}
        results: list[PaperRealtimeQuoteModel] = []
        for item in universe:
            quote = quotes_by_code.get(item.code)
            price = _to_float(quote[chr(112) + chr(114) + chr(105) + chr(99) + chr(101)]) if quote else None
            position = positions.get(item.code)
            quantity = position.quantity if position else 0
            avg_cost = float(position.avg_cost) if position and position.avg_cost else None
            unrealized_pnl = None
            unrealized_pnl_rate = None
            if position and price and avg_cost:
                pnl = (price - avg_cost) * quantity
                cost = avg_cost * quantity
                unrealized_pnl = round(pnl, 2)
                unrealized_pnl_rate = round(pnl / cost, 4) if cost > 0 else None
            results.append(
                PaperRealtimeQuoteModel(
                    code=item.code,
                    name=item.name,
                    price=price,
                    snapshot_time=quote[
                        chr(115)
                        + chr(110)
                        + chr(97)
                        + chr(112)
                        + chr(115)
                        + chr(104)
                        + chr(111)
                        + chr(116)
                        + chr(95)
                        + chr(116)
                        + chr(105)
                        + chr(109)
                        + chr(101)
                    ]
                    if quote
                    else None,
                    quantity=quantity,
                    avg_cost=avg_cost,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_rate=unrealized_pnl_rate,
                )
            )
        return results

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
            universe_names = {item.code: item.name for item in universe}
            signal_notifications: list[FeishuSignal] = []
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
                paper_signal = await cls._upsert_signal(
                    db,
                    account.id,
                    item.code,
                    today,
                    execute_date,
                    signal['signal'],
                    signal['reason'],
                    close,
                    reset_status=False,
                )
                signal_notifications.append(
                    FeishuSignal(
                        code=item.code,
                        name=universe_names.get(item.code),
                        signal=signal['signal'],
                        price=close,
                        reason=signal['reason'],
                        signal_id=paper_signal.id,
                        account_id=account.id,
                    )
                )

            await cls._upsert_snapshot(db, account)
            await db.commit()
        logger.bind(today=today, execute_date=execute_date, count=len(universe)).info('模拟盘收盘信号计算完成')
        _notify_task = asyncio.create_task(cls._notify_eod_summary(signal_notifications, today))
        del _notify_task

    # ---------------------------------------------------------------- 实时轮循
    @classmethod
    async def run_realtime_signal_and_execute(cls) -> dict[str, Any]:
        """每分钟轮循标的池实时行情，信号变化时立即撮合并刷新当日净值快照。"""
        now = datetime.now(TimezoneUtil.get_app_timezone())
        today = now.date().isoformat()
        if not cls._is_trading_day(today):
            logger.bind(today=today).info('非交易日，跳过模拟盘实时轮循')
            return {'executed': 0, 'skipped': 0, 'message': '非交易日，跳过实时轮循'}
        if not cls._is_trading_time(now):
            logger.bind(today=today, time=now.strftime('%H:%M:%S')).info('非交易时段，跳过模拟盘实时轮循')
            return {'executed': 0, 'skipped': 0, 'message': '非交易时段，跳过实时轮循'}

        async with DataSourceRegistry.session(log_sql=False) as db:
            account = await StockPaperDao.get_account(db, DEFAULT_ACCOUNT_NAME)
            if account is None or account.status != 'active':
                logger.bind(today=today).info('模拟账户未初始化或非激活，跳过实时轮循')
                return {'executed': 0, 'skipped': 0, 'message': '模拟账户未初始化或非激活'}
            if not account.strategy_name:
                logger.bind(today=today).warning('模拟账户未配置策略，跳过实时轮循')
                return {'executed': 0, 'skipped': 0, 'message': '模拟账户未配置策略'}

            universe = await StockPaperDao.get_universe(db, account.id)
            if not universe:
                logger.bind(today=today).info('模拟盘标的池为空，跳过实时轮循')
                return {'executed': 0, 'skipped': 0, 'message': '模拟盘标的池为空'}

            codes = [item.code for item in universe]
            universe_names = {item.code: item.name for item in universe}
            positions = {p.code: p for p in await StockPaperDao.list_positions(db, account.id)}
            active_count = max(len(codes), 1)
            quotes = await StockRealtimeService.fetch_realtime(codes)
            quotes_by_code = {q['code']: q for q in quotes}

            executed_count = 0
            skipped_count = 0
            signal_notifications: list[FeishuSignal] = []
            for code in codes:
                notification, status = await cls._process_realtime_symbol(
                    db,
                    account,
                    code,
                    universe_names.get(code),
                    quotes_by_code.get(code),
                    positions,
                    today,
                    active_count,
                )
                if status == 'executed':
                    executed_count += 1
                elif status == 'skipped':
                    skipped_count += 1
                if notification is not None:
                    signal_notifications.append(notification)

            await cls._upsert_snapshot(db, account)
            await db.commit()

        message = f'模拟盘实时轮循完成：撮合{executed_count}笔，跳过{skipped_count}只'
        logger.bind(today=today, executed_count=executed_count, skipped_count=skipped_count).info(message)
        if signal_notifications:
            _notify_task = asyncio.create_task(cls._notify_realtime_signals(signal_notifications))
            del _notify_task
        return {'executed': executed_count, 'skipped': skipped_count, 'message': message}

    @classmethod
    async def _notify_eod_summary(cls, signal_notifications: list[FeishuSignal], today: str) -> None:
        """后台发送飞书收盘信号汇总并保存消息凭据，避免阻塞主 session。"""
        try:
            summary_result = await FeishuNotificationService.send_signal_summary_with_receipt(signal_notifications, today)
            await cls._save_feishu_receipt('signal_summary', None, None, summary_result)
        except Exception as exc:
            logger.bind(channel='feishu', today=today).warning(f'飞书收盘信号通知发送/凭据保存失败：{exc}')

    @classmethod
    async def _notify_realtime_signals(cls, signal_notifications: list[FeishuSignal]) -> None:
        """后台发送飞书实时交易信号并保存消息凭据，避免阻塞主 session。"""
        try:
            for signal_notification in signal_notifications:
                send_result = await FeishuNotificationService.send_signal_with_receipt(signal_notification)
                await cls._save_feishu_receipt(
                    'signal',
                    signal_notification.signal_id,
                    signal_notification.code,
                    send_result,
                    account_id=signal_notification.account_id,
                )
        except Exception as exc:
            logger.bind(channel='feishu').warning(f'飞书实时信号通知发送/凭据保存失败：{exc}')
    @staticmethod
    async def _save_feishu_receipt(
        message_type: str,
        signal_id: int | None,
        code: str | None,
        send_result: FeishuSendResult,
        db: AsyncSession | None = None,
        account_id: int | None = None,
    ) -> None:
        """保存企业自建应用机器人消息凭据，用于后续撤回。"""
        if not send_result.ok or not send_result.message_id:
            return

        try:

            async def _create(current_db: AsyncSession) -> None:
                await StockPaperDao.create_feishu_message(
                    current_db,
                    StockFeishuMessage(
                        message_type=message_type,
                        signal_id=signal_id,
                        account_id=account_id,
                        code=code,
                        message_id=send_result.message_id,
                        chat_id=FeishuNotifyConfig.feishu_chat_id,
                    ),
                )

            if db is None:
                async with DataSourceRegistry.session(log_sql=False) as receipt_db:
                    await _create(receipt_db)
                    await receipt_db.commit()
            else:
                await _create(db)
        except Exception as exc:
            logger.bind(channel='feishu', message_id=send_result.message_id).warning(
                f'保存飞书消息凭据失败（不影响主流程）：{exc}'
            )

    @classmethod
    async def recall_signal_notification(cls, db: AsyncSession, signal_id: int, reason: str) -> dict[str, Any]:
        """撤回指定交易信号的飞书通知，并更新消息凭据状态。"""
        message = await StockPaperDao.get_feishu_message_by_signal(db, signal_id, 'signal')
        if message is None:
            raise ServiceException(message='该信号没有可撤回的飞书通知')
        if message.recall_status == 'recalled':
            raise ServiceException(message='该飞书通知已撤回')

        recall_result = await FeishuNotificationService.recall_message(message.message_id)
        now = datetime.now(TimezoneUtil.get_app_timezone())
        if recall_result.ok:
            await StockPaperDao.update_feishu_message(
                db,
                message.id,
                recall_status='recalled',
                recall_reason=reason,
                recalled_at=now,
            )
            await db.commit()
            return {'message_id': message.message_id, 'status': 'recalled'}

        await StockPaperDao.update_feishu_message(
            db,
            message.id,
            recall_status='failed',
            recall_reason=(recall_result.error_message or '')[:500],
        )
        await db.commit()
        return {
            'message_id': message.message_id,
            'status': 'failed',
            'error_message': recall_result.error_message or '飞书消息撤回失败',
        }

    @classmethod
    async def _process_realtime_symbol(
        cls,
        db: AsyncSession,
        account: StockPaperAccount,
        code: str,
        name: str | None,
        quote: dict[str, Any] | None,
        positions: dict[str, StockPaperPosition],
        today: str,
        active_count: int,
    ) -> tuple[FeishuSignal | None, str]:
        """处理单只标的实时信号，返回待通知信号与处理状态。"""
        price = _to_float(quote['price']) if quote is not None else None
        if price is None or price <= 0:
            logger.bind(code=code, today=today).warning('未获取到实时价，跳过该标的实时信号')
            return None, 'skipped'

        position = positions.get(code)
        if position is not None:
            await StockPaperDao.update_position(db, position.id, last_price=price)
            position.last_price = price

        signal = await asyncio.to_thread(
            StockSignalService.compute_signal,
            account.strategy_name,
            code,
            {},
            today,
            price,
        )
        direction = signal.get('signal') or '持有'
        reason = signal.get('reason') or ''
        existing = await StockPaperDao.get_signal(db, account.id, code, today)
        should_notify = direction in ('买入', '卖出') and (existing is None or existing.signal != direction)

        if existing is not None and existing.signal == direction:
            await cls._upsert_signal(db, account.id, code, today, today, direction, reason, price, reset_status=False)
            return None, 'unchanged'

        sig = await cls._upsert_signal(db, account.id, code, today, today, direction, reason, price, reset_status=True)
        total_equity = cls._account_equity(account, list(positions.values()))['total_equity']
        if direction == '买入':
            await cls._execute_buy(db, account, sig, name, positions, total_equity, active_count, price)
        elif direction == '卖出':
            await cls._execute_sell(db, account, sig, name, positions, price)
        else:
            await StockPaperDao.update_signal(db, sig.id, status='executed')
            sig.status = 'executed'
        await db.flush()

        notification = None
        if should_notify:
            notification = FeishuSignal(
                code=code,
                name=name,
                signal=direction,
                price=price,
                reason=reason,
                signal_id=sig.id,
                account_id=account.id,
            )
        return notification, 'executed'

    # ---------------------------------------------------------------- 标的池日线同步
    @classmethod
    async def run_daily_sync(cls) -> dict[str, Any]:
        """开盘前同步标的池日线数据到MongoDB，确保收盘信号使用最新K线。"""
        today = cls._today()
        if not cls._is_trading_day(today):
            logger.bind(today=today).info('非交易日，跳过标的池日线同步')
            return {'synced': [], 'failed': {}, 'message': '非交易日，跳过日线同步'}

        async with DataSourceRegistry.session(log_sql=False) as db:
            account = await StockPaperDao.get_account(db, DEFAULT_ACCOUNT_NAME)
            if account is None or account.status != 'active':
                logger.bind(today=today).info('模拟账户未初始化或非激活，跳过日线同步')
                return {'synced': [], 'failed': {}, 'message': '模拟账户未初始化或非激活'}

            universe = await StockPaperDao.get_universe(db, account.id)
            if not universe:
                logger.bind(today=today).info('模拟盘标的池为空，跳过日线同步')
                return {'synced': [], 'failed': {}, 'message': '模拟盘标的池为空'}

        codes = [item.code for item in universe]
        now = datetime.now(TimezoneUtil.get_app_timezone())
        start_date = (now - timedelta(days=30)).date()
        end_date = now.date()

        synced: list[str] = []
        failed: dict[str, str] = {}
        for code in codes:
            succeeded, error = await cls._sync_single_stock_day(code, start_date, end_date)
            if succeeded:
                synced.append(code)
            else:
                failed[code] = error or str(error)
                logger.bind(code=code).warning(f'标的{code}日线同步失败：{error}')

        message = f'标的池日线同步完成：成功{len(synced)}只，失败{len(failed)}只'
        logger.bind(today=today, synced_count=len(synced), failed_count=len(failed)).info(message)
        return {'synced': synced, 'failed': failed, 'message': message}

    @staticmethod
    async def _sync_single_stock_day(code: str, start_date: date, end_date: date) -> tuple[bool, str | None]:
        """同步单只标的日线，返回是否成功与失败原因。"""
        try:
            query = StockDayImportModel(code=code, start=start_date, end=end_date)
            await StockDayService.import_stock_day_data(query)
            return True, None
        except ServiceException as exc:
            return False, exc.message or str(exc)
        except Exception as exc:
            return False, str(exc)

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
        *,
        reset_status: bool = True,
    ) -> StockPaperSignal:
        existing = await StockPaperDao.get_signal(db, account_id, code, signal_date)
        if existing is None:
            return await StockPaperDao.create_signal(
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
        status = 'pending' if reset_status or existing.signal != signal else existing.status
        await StockPaperDao.update_signal(
            db,
            existing.id,
            signal=signal,
            reason=reason,
            close_price=close_price,
            execute_date=execute_date,
            status=status,
        )
        existing.signal = signal
        existing.reason = reason
        existing.close_price = close_price
        existing.execute_date = execute_date
        existing.status = status
        return existing

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
            await StockPaperDao.create_snapshot(
                db, StockPaperDailySnapshot(account_id=account.id, date=today, **values)
            )
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
        db_pos = await StockPaperDao.get_position_by_code(db, account.id, signal.code)
        if db_pos is not None and db_pos.quantity > 0:
            positions[signal.code] = db_pos
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

        account.cash = float(account.cash) - total_cost
        position = positions.get(signal.code)
        if position is None:
            position = await StockPaperDao.create_position(
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
            positions[signal.code] = position
        else:
            new_quantity = position.quantity + quantity
            new_cost = (float(position.avg_cost) * position.quantity + amount) / new_quantity
            await StockPaperDao.update_position(
                db, position.id, quantity=new_quantity, avg_cost=new_cost, last_price=float(price)
            )
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
                trade_time=cls._now_hms(),
            ),
        )
        await StockPaperDao.update_signal(db, signal.id, status='executed')
        signal.status = 'executed'
        _notify_task = asyncio.create_task(
            cls._notify_trade_executed(
                code=signal.code,
                name=name,
                side='买入',
                price=float(price),
                quantity=quantity,
                amount=amount,
                commission=commission,
                stamp_tax=0.0,
                signal_id=signal.id,
                account_id=account.id,
            )
        )
        del _notify_task

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
        db_pos = await StockPaperDao.get_position_by_code(db, account.id, signal.code)
        if db_pos is not None:
            positions[signal.code] = db_pos
            position = db_pos
        else:
            position = None
        if position is None or position.available_quantity <= 0:
            await cls._mark_skipped(db, account.id, signal, name, price, '无可用持仓可卖（T+1）')
            return

        quantity = int(position.available_quantity)
        amount = float(quantity) * float(price)
        commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
        stamp_tax = amount * STAMP_TAX_RATE
        account.cash = float(account.cash) + amount - commission - stamp_tax
        if position.quantity == quantity:
            await StockPaperDao.delete_positions_by_code(db, account.id, signal.code)
            positions.pop(signal.code, None)
        else:
            await StockPaperDao.update_position(
                db,
                position.id,
                quantity=position.quantity - quantity,
                available_quantity=position.available_quantity - quantity,
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
                trade_time=cls._now_hms(),
            ),
        )
        await StockPaperDao.update_signal(db, signal.id, status='executed')
        signal.status = 'executed'
        _notify_task = asyncio.create_task(
            cls._notify_trade_executed(
                code=signal.code,
                name=name,
                side='卖出',
                price=float(price),
                quantity=quantity,
                amount=amount,
                commission=commission,
                stamp_tax=stamp_tax,
                signal_id=signal.id,
                account_id=account.id,
            )
        )
        del _notify_task

    @classmethod
    async def _notify_trade_executed(
        cls,
        code: str,
        name: str | None,
        side: str,
        price: float,
        quantity: int,
        amount: float,
        commission: float,
        stamp_tax: float,
        signal_id: int | None = None,
        account_id: int | None = None,
    ) -> None:
        """后台发送飞书成交提示消息并保存消息凭据，避免阻塞撮合主流程。"""
        try:
            text = (
                '【模拟交易成交】\n'
                f'股票：{code} {name or ""}\n'
                f'方向：{side}\n'
                f'成交价：{price:.2f}\n'
                f'数量：{quantity}\n'
                f'金额：{amount:,.2f}\n'
                f'佣金：{commission:.2f}\n'
                f'印花税：{stamp_tax:.2f}\n'
                f'时间：{cls._now_hms()}'
            )
            send_result = await FeishuNotificationService.send_text_with_receipt(text)
            await cls._save_feishu_receipt('trade', signal_id, code, send_result, account_id=account_id)
        except Exception as exc:
            logger.bind(channel='feishu', code=code).warning(f'飞书成交通知发送/凭据保存失败：{exc}')

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
                trade_time=cls._now_hms(),
            ),
        )
        await StockPaperDao.update_signal(db, signal.id, status='skipped')
        signal.status = 'skipped'

    # ---------------------------------------------------------------- 勾选入池
    @classmethod
    async def ensure_account(
        cls, db: AsyncSession, strategy_name: str | None = None, initial_cash: int = 1_000_000
    ) -> StockPaperAccount:
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
                    StockPaperUniverse(
                        account_id=account.id, code=code, name=name, source_batch_id=batch_id, status='active'
                    ),
                )
            else:
                await StockPaperDao.update_universe_by_code(
                    db, account.id, code, name=name, source_batch_id=batch_id, status='active'
                )
            added_count += 1
        await db.commit()
        logger.bind(
            batch_id=batch_id, account_id=account.id, added_count=added_count, skipped_count=skipped_count
        ).info('回测结果已勾选加入模拟盘标的池')
        return {'accountId': account.id, 'addedCount': added_count, 'skippedCount': skipped_count}
