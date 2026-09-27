"""Safe strategy discovery and asynchronous Backtrader execution."""

import ast
import asyncio
import contextlib
import io
import math
import re
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.database import DataSourceRegistry
from exceptions.exception import ServiceException
from utils.log_util import logger
from module_stock.dao.stock_strategy_dao import StockStrategyDao
from module_stock.entity.do.stock_strategy_do import StockStrategyRun
from module_stock.entity.vo.stock_strategy_vo import (
    StrategyDetailModel,
    StrategyHistoryQueryModel,
    StrategyListModel,
    StrategyRunDetailModel,
    StrategyRunRequest,
    StrategyRunStatusModel,
)

_STRATEGY_NAME = re.compile(r'^[a-z][a-z0-9_]*$')
_ROOT = Path(__file__).resolve().parents[2]
_STRATEGY_DIR = _ROOT / 'youw_test' / 'strategies'
_RUNNING_TASKS: set[asyncio.Task[None]] = set()


def _log_task_result(task: asyncio.Task[None]) -> None:
    """Record crashes that escape the background task wrapper."""
    _RUNNING_TASKS.discard(task)
    if task.cancelled():
        logger.bind(task_name=task.get_name()).warning('股票策略回测任务已取消')
        return
    if exc := task.exception():
        logger.bind(task_name=task.get_name()).error(f'股票策略回测任务未捕获异常：{type(exc).__name__}: {exc}')


class StockStrategyService:
    @classmethod
    def _file(cls, name: str) -> Path:
        if not _STRATEGY_NAME.fullmatch(name):
            raise ServiceException(message='非法策略名称')
        path = (_STRATEGY_DIR / f'{name}.py').resolve()
        if path.parent != _STRATEGY_DIR.resolve() or not path.is_file() or name == 'base':
            raise ServiceException(message='策略不存在')
        return path

    @classmethod
    def _metadata(cls, path: Path) -> dict[str, Any]:
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(path))
        values: dict[str, Any] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {'DISPLAY_NAME', 'CATEGORY', 'DESCRIPTION'}:
                        try:
                            values[target.id] = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            pass
        if not any(isinstance(node, ast.ClassDef) and node.name == 'Strategy' for node in tree.body):
            raise ValueError('策略模块必须定义Strategy类')
        docstring = values.get('DESCRIPTION') or ast.get_docstring(tree) or '未提供策略说明'
        display_name = values.get('DISPLAY_NAME') or path.stem.replace('_', ' ').title()
        return {
            'name': path.stem,
            'display_name': str(display_name),
            'category': str(values.get('CATEGORY', 'code')),
            'description': str(docstring).splitlines()[0],
            'modified_time': datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec='seconds'),
            'source_code': source,
        }

    @classmethod
    async def list_strategies(cls, db: AsyncSession) -> list[StrategyListModel]:
        summaries = await StockStrategyDao.summaries(db)
        result = []
        for path in sorted(_STRATEGY_DIR.glob('*.py')):
            if path.name.startswith('_') or path.stem == 'base':
                continue
            try:
                metadata = cls._metadata(path)
            except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
                continue
            stat = summaries.get(path.stem, {})
            last = stat.get('last')
            summary = (last.summary or {}) if last else {}
            result.append(
                StrategyListModel(
                    **{key: metadata[key] for key in ('name', 'display_name', 'category', 'description', 'modified_time')},
                    run_count=stat.get('run_count', 0),
                    last_run_time=last.create_time.isoformat() if last and last.create_time else None,
                    last_return_rate=summary.get('returnRate'),
                    last_status=last.status if last else None,
                )
            )
        return result

    @classmethod
    async def detail(cls, strategy_name: str) -> StrategyDetailModel:
        metadata = cls._metadata(cls._file(strategy_name))
        parameters = await asyncio.to_thread(cls._load_parameters, strategy_name)
        return StrategyDetailModel(**metadata, parameters=parameters)

    @staticmethod
    def _load_parameters(strategy_name: str) -> list[dict[str, Any]]:
        try:
            from youw_test.strategies import load_strategy

            strategy = load_strategy(strategy_name)
            params = strategy.params
            return [{'name': key, 'default': value, 'type': type(value).__name__} for key, value in params._getitems()]
        except Exception:
            # Source can still be inspected when optional backtest dependencies are unavailable.
            return []

    @classmethod
    def _coerce_strategy_params(cls, strategy_name: str, values: dict[str, Any]) -> dict[str, Any]:
        definitions = {item['name']: item for item in cls._load_parameters(strategy_name)}
        invalid = set(values).difference(definitions)
        if invalid:
            raise ServiceException(message=f'策略参数不合法：{", ".join(sorted(invalid))}')

        converted: dict[str, Any] = {}
        for name, value in values.items():
            expected_type = definitions[name]['type']
            try:
                if expected_type == 'bool':
                    if isinstance(value, bool):
                        converted[name] = value
                    elif isinstance(value, str) and value.lower() in {'true', 'false'}:
                        converted[name] = value.lower() == 'true'
                    else:
                        raise ValueError
                elif expected_type == 'int':
                    number = float(value)
                    if not number.is_integer():
                        raise ValueError
                    converted[name] = int(number)
                elif expected_type == 'float':
                    converted[name] = float(value)
                elif expected_type == 'str':
                    converted[name] = str(value)
                else:
                    converted[name] = value
            except (TypeError, ValueError, OverflowError) as exc:
                raise ServiceException(message=f'策略参数{name}必须为{expected_type}类型') from exc
        return converted

    @classmethod
    async def create_run(cls, db: AsyncSession, request: StrategyRunRequest) -> str:
        cls._file(request.strategy_name)
        strategy_params = await asyncio.to_thread(
            cls._coerce_strategy_params,
            request.strategy_name,
            request.strategy_params,
        )
        run_id = str(uuid.uuid4())
        await StockStrategyDao.create(
            db,
            StockStrategyRun(
                run_id=run_id,
                strategy_name=request.strategy_name,
                code=request.code,
                start_date=request.start.isoformat(),
                end_date=request.end.isoformat(),
                initial_cash=request.initial_cash,
                commission_rate=str(request.commission_rate),
                stamp_tax_rate=str(request.stamp_tax_rate),
                benchmark_code=request.benchmark_code,
                strategy_params=strategy_params,
                status='pending',
                progress=0,
            ),
        )
        await db.commit()
        logger.bind(
            run_id=run_id,
            strategy_name=request.strategy_name,
            code=request.code,
            start_date=request.start.isoformat(),
            end_date=request.end.isoformat(),
            initial_cash=request.initial_cash,
            benchmark_code=request.benchmark_code,
            strategy_params=strategy_params,
        ).info('股票策略回测已提交')
        task = asyncio.create_task(cls._execute_run(run_id), name=f'stock-strategy-{run_id}')
        _RUNNING_TASKS.add(task)
        task.add_done_callback(_log_task_result)
        return run_id

    @classmethod
    async def _execute_run(cls, run_id: str) -> None:
        logger.bind(run_id=run_id).info('股票策略回测任务开始')
        try:
            async with DataSourceRegistry.session(log_sql=False) as db:
                await StockStrategyDao.update(db, run_id, status='running', progress=5, error_message=None)
                await db.commit()
                run = await StockStrategyDao.get(db, run_id)
        except Exception:
            logger.bind(run_id=run_id).exception('股票策略回测加载记录失败')
            raise
        if run is None:
            logger.bind(run_id=run_id).error('股票策略回测记录不存在，任务终止')
            return
        run_context = {
            'run_id': run.run_id,
            'strategy_name': run.strategy_name,
            'code': run.code,
            'start_date': run.start_date,
            'end_date': run.end_date,
            'benchmark_code': run.benchmark_code,
        }
        logger.bind(**run_context).info(f'股票策略回测开始执行：{run.strategy_name}')
        try:
            result = await asyncio.to_thread(cls._run_backtest, run)
            logger.bind(run_id=run_id).info('股票策略回测结果已生成，准备写入数据库')
            async with DataSourceRegistry.session(log_sql=False) as db:
                await StockStrategyDao.update(db, run_id, status='success', progress=100, **result)
                await db.commit()
            logger.bind(run_id=run_id).info('股票策略回测成功结果已写入数据库')
            logger.bind(
                **run_context,
                trade_count=result['summary'].get('tradeCount'),
                return_rate=result['summary'].get('returnRate'),
            ).info('股票策略回测执行成功')
        except Exception as exc:
            error_value = repr(exc) if isinstance(exc, KeyError) else exc
            error_message = f'{type(exc).__name__}: {error_value}'[:4000]
            logger.bind(**run_context).exception(f'股票策略回测执行失败：{error_message}')
            try:
                async with DataSourceRegistry.session(log_sql=False) as db:
                    await StockStrategyDao.update(
                        db, run_id, status='failed', progress=100, error_message=error_message, run_logs=traceback.format_exc().splitlines()
                    )
                    await db.commit()
            except Exception:
                logger.bind(run_id=run_id).exception('股票策略回测失败状态写入数据库失败')

    @staticmethod
    def _strategy_warmup_bars(strategy_cls: type, strategy_params: dict[str, Any] | None) -> int:
        """Estimate how many historical bars indicators need before the live run."""
        period_keys = ('period', 'lookback', 'window')
        periods = []
        for name, default in strategy_cls.params._getitems():
            value = (strategy_params or {}).get(name, default)
            if any(key in name for key in period_keys) and isinstance(value, (int, float)) and value > 0:
                periods.append(int(value))
        return max(periods, default=0) + 5

    @staticmethod
    def _warmup_start_date(start_date: str, warmup_bars: int) -> str:
        """Convert a bar-count warmup into a calendar start date."""
        start = datetime.strptime(str(start_date)[:10], '%Y-%m-%d').date()
        return (start - timedelta(days=warmup_bars * 3 + 10)).isoformat()

    @staticmethod
    def _live_start_strategy(strategy_cls: type, live_start_date):
        """Allow the prior close to fill on the requested start date."""
        class _LiveStartStrategy(strategy_cls):
            def next(self):
                if self.datas[0].datetime.date(0) < live_start_date:
                    return
                super().next()

        return _LiveStartStrategy

    @classmethod
    def _run_backtest(cls, run: StockStrategyRun) -> dict[str, Any]:
        try:
            import backtrader as bt
            from youw_test.strategies import load_strategy
        except ImportError as exc:
            raise RuntimeError('缺少 Backtrader、QUANTAXIS 或其运行依赖') from exc

        strategy_cls = load_strategy(run.strategy_name)
        strategy_params = run.strategy_params or {}
        warmup_bars = cls._strategy_warmup_bars(strategy_cls, strategy_params)
        data_start_date = cls._warmup_start_date(run.start_date, warmup_bars)
        requested_start_date = datetime.strptime(str(run.start_date)[:10], '%Y-%m-%d').date()

        logger.bind(
            run_id=run.run_id,
            strategy_name=run.strategy_name,
            code=run.code,
            start_date=run.start_date,
            end_date=run.end_date,
        ).info('股票策略回测正在加载行情数据')
        logs = io.StringIO()
        with contextlib.redirect_stdout(logs):
            data = cls._load_stock_data(run.code, data_start_date, run.end_date)
            if data is None:
                raise RuntimeError(f'未查询到股票{run.code}在{data_start_date}至{run.end_date}的日线数据，请先导入行情数据')
            available_dates = list(data.index)
            first_live_fill_date = next(
                (day for day in available_dates if day.date() >= requested_start_date),
                available_dates[-1],
            )
            prior_dates = [day for day in available_dates if day.date() < first_live_fill_date.date()]
            signal_start_date = max(prior_dates).date() if prior_dates else first_live_fill_date.date()
            logger.bind(
                run_id=run.run_id,
                data_rows=len(data),
                data_start=str(data.index.min()),
                data_end=str(data.index.max()),
                warmup_bars=warmup_bars,
                requested_start=str(requested_start_date),
                signal_start=str(signal_start_date),
                first_fill=str(first_live_fill_date.date()),
            ).info('股票策略回测行情数据加载完成')
            cerebro = bt.Cerebro()
            cerebro.adddata(bt.feeds.PandasData(dataname=data), name=run.code)

            # 组合策略可以通过 UNIVERSE 声明多个标的；主时钟标的本身不要重复加入。
            universe = [
                code for code in (getattr(strategy_cls, 'UNIVERSE', None) or [])
                if code != run.code
            ]
            for universe_code in universe:
                universe_data = cls._load_stock_data(universe_code, data_start_date, run.end_date)
                if universe_data is None:
                    logger.bind(run_id=run.run_id, universe_code=universe_code).warning('组合策略标的未加载到数据，已跳过')
                    continue
                cerebro.adddata(
                    bt.feeds.PandasData(dataname=universe_data),
                    name=universe_code,
                )
            logger.bind(run_id=run.run_id, feeds=len(cerebro.datas)).info('组合策略行情数据加载完成')

            cerebro.addstrategy(
                cls._live_start_strategy(strategy_cls, signal_start_date),
                **strategy_params,
            )
            cerebro.broker.setcash(run.initial_cash)

            # A股卖出额外收取印花税；原版 JoinQuant 设置为千分之一。
            # Backtrader 默认只有买卖同一佣金，因此这里用自定义佣金方案。
            class _StockCommissionInfo(bt.CommissionInfo):
                params = (
                    ('commission', 0.0),
                    ('stamp_duty', 0.001),
                    ('min_commission', 5.0),
                )

                def _getcommission(self, size, price, pseudoexec):
                    turnover = abs(size) * price
                    # 原版策略的“最低佣金5元”只作用于佣金，不作用于印花税。
                    commission = max(turnover * self.p.commission, self.p.min_commission)
                    if size < 0:
                        commission += turnover * self.p.stamp_duty
                    return commission

            cerebro.broker.addcommissioninfo(
                _StockCommissionInfo(
                    commission=float(run.commission_rate),
                    stamp_duty=float(run.stamp_tax_rate),
                    min_commission=5.0,
                )
            )
            cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='returns')
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
            cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
            start_value = cerebro.broker.getvalue()
            strategies = cerebro.run()
            strategy = strategies[0]
            end_value = cerebro.broker.getvalue()
        logger.bind(
            run_id=run.run_id,
            initial_cash=float(start_value),
            ending_value=float(end_value),
        ).info('股票策略回测引擎执行完成')

        returns = strategy.analyzers.returns.get_analysis()
        equity, dates = [], []
        value = float(start_value)
        for day, rate in returns.items():
            date_str = str(day)[:10]
            if date_str < str(run.start_date)[:10]:
                continue
            value *= 1 + float(rate or 0)
            dates.append(date_str)
            equity.append(round(value, 2))
        drawdown = strategy.analyzers.drawdown.get_analysis()
        trade = strategy.analyzers.trades.get_analysis()
        # TradeAnalyzer uses AutoOrderedDict; getattr() is unsafe here because a
        # missing key raises KeyError instead of AttributeError.
        trade_total = trade.get('total') or {}
        trade_won = trade.get('won') or {}
        trade_lost = trade.get('lost') or {}
        closed = int(trade_total.get('closed', 0) or 0)
        won = int(trade_won.get('total', 0) or 0)
        gross_win = float((trade_won.get('pnl') or {}).get('total', 0) or 0)
        gross_loss = abs(float((trade_lost.get('pnl') or {}).get('total', 0) or 0))
        benchmark = None
        if run.benchmark_code:
            benchmark_data = cls._load_stock_data(run.benchmark_code, run.start_date, run.end_date)
            if benchmark_data is None:
                raise RuntimeError(f'未查询到基准{run.benchmark_code}在{run.start_date}至{run.end_date}的日线数据')
            close = benchmark_data['close']
            benchmark_by_date = {
                str(day)[:10]: round(float(price / close.iloc[0] - 1), 6) for day, price in close.items()
            }
            benchmark = [benchmark_by_date.get(day) for day in dates]
        strategy_return = float(end_value / start_value - 1)
        benchmark_return = next((value for value in reversed(benchmark or []) if value is not None), None)
        summary = {
            'returnRate': strategy_return,
            'annualReturn': (1 + strategy_return) ** (252 / max(len(equity), 1)) - 1,
            'benchmarkReturn': benchmark_return,
            'excessReturn': strategy_return - benchmark_return if benchmark_return is not None else None,
            'sharpeRatio': cls._finite(strategy.analyzers.sharpe.get_analysis().get('sharperatio')),
            'maxDrawdown': float((drawdown.get('max') or {}).get('drawdown', 0) or 0) / 100,
            'winRate': won / closed if closed else 0,
            'profitLossRatio': cls._finite(gross_win / gross_loss) if gross_loss else None,
            'tradeCount': closed,
            'initialCash': float(start_value),
            'endingValue': float(end_value),
        }
        strategy_returns = [round(item / start_value - 1, 6) for item in equity]
        peak = -math.inf
        drawdown_curve = []
        for value in equity:
            peak = max(peak, value)
            drawdown_curve.append(round(value / peak - 1, 6) if peak else 0)
        logger.bind(run_id=run.run_id, equity_points=len(equity), trade_count=closed).info('股票策略回测结果处理完成')
        curves = {
            'dates': dates,
            'strategyEquity': equity,
            'strategyReturn': strategy_returns,
            'benchmarkReturn': benchmark,
            'excessReturn': [
                round(strategy_returns[index] - benchmark[index], 6) if benchmark[index] is not None else None
                for index in range(len(strategy_returns))
            ] if benchmark else None,
            'drawdown': drawdown_curve,
        }
        trades = [
            record for record in getattr(strategy, 'execution_records', [])
            if record.get('date', '') >= str(run.start_date)[:10]
        ]
        return {'summary': summary, 'curves': curves, 'trades': trades, 'run_logs': logs.getvalue().splitlines()}

    @staticmethod
    def _load_qa_daily_data(code: str, start: str, end: str, index: bool = False):
        try:
            import pandas as pd
            import QUANTAXIS as QA
        except ImportError as exc:
            raise RuntimeError('缺少 QUANTAXIS 或 pandas，无法加载行情数据') from exc

        fetcher = getattr(QA, 'QA_fetch_index_day_adv' if index else 'QA_fetch_stock_day_adv', None)
        if fetcher is None:
            return None
        stock_data = fetcher(code, start, end)
        if stock_data is None or stock_data.data.empty:
            return None
        data = stock_data.data.reset_index().copy()
        data['datetime'] = pd.to_datetime(data['date'])
        data = data.set_index('datetime')
        columns = ['open', 'high', 'low', 'close', 'volume']
        data[columns] = data[columns].apply(pd.to_numeric, errors='coerce')
        data = data.dropna(subset=columns)
        return data[columns].sort_index() if not data.empty else None

    @staticmethod
    def _load_tencent_etf_data(code: str, start: str, end: str):
        from youw_test.strategies.etf_data import fetch_etf_daily

        return fetch_etf_daily(code, start, end)

    @classmethod
    def _load_stock_data(cls, code: str, start: str, end: str):
        """兼容股票、指数和腾讯ETF前复权日线的统一入口。"""
        data = cls._load_qa_daily_data(code, start, end, index=False)
        if data is not None:
            return data
        data = cls._load_qa_daily_data(code, start, end, index=True)
        if data is not None:
            return data
        return cls._load_tencent_etf_data(code, start, end)
    @staticmethod
    def _finite(value: Any) -> float | None:
        if value is None:
            return None
        number = float(value)
        return number if math.isfinite(number) else None

    @classmethod
    def _status_model(cls, run: StockStrategyRun, detail: bool = False):
        payload = dict(
            run_id=run.run_id,
            strategy_name=run.strategy_name,
            status=run.status,
            progress=run.progress,
            error_message=run.error_message,
            summary=run.summary,
        )
        if not detail:
            return StrategyRunStatusModel(**payload)
        return StrategyRunDetailModel(
            **payload,
            code=run.code,
            start=run.start_date,
            end=run.end_date,
            initial_cash=run.initial_cash,
            commission_rate=float(run.commission_rate),
            stamp_tax_rate=float(run.stamp_tax_rate),
            benchmark_code=run.benchmark_code,
            strategy_params=run.strategy_params or {},
            create_time=run.create_time,
            curves=run.curves,
            trades=run.trades,
            logs=run.run_logs,
        )

    @classmethod
    async def status(cls, db: AsyncSession, run_id: str, detail: bool = False):
        run = await StockStrategyDao.get(db, run_id)
        if run is None:
            logger.bind(run_id=run_id).warning('查询的股票策略回测记录不存在')
            raise ServiceException(message='回测记录不存在')
        logger.bind(run_id=run_id, status=run.status, progress=run.progress, detail=detail).debug('查询股票策略回测状态')
        return cls._status_model(run, detail)

    @classmethod
    async def history(cls, db: AsyncSession, strategy_name: str, query: StrategyHistoryQueryModel):
        cls._file(strategy_name)
        return await StockStrategyDao.list_for_strategy(db, strategy_name, query.page_num, query.page_size)

    @classmethod
    async def recover_orphaned_runs(cls) -> None:
        async with DataSourceRegistry.session(log_sql=False) as db:
            await StockStrategyDao.fail_orphaned(db)
            await db.commit()
        logger.info('股票策略遗留回测任务恢复检查完成')
