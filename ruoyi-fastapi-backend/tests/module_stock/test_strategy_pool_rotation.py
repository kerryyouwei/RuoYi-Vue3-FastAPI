"""股票池轮动策略与滚动验证单元测试。"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import backtrader as bt
import pandas as pd
import pytest
from pydantic import ValidationError

from module_stock.dao.stock_pool_dao import StockPoolDao
from module_stock.dao.stock_scan_dao import StockScanDao
from module_stock.entity.vo.stock_paper_vo import ScanRunRequestModel
from module_stock.entity.vo.stock_strategy_vo import StrategyRunRequest, StrategyValidateRequest
from module_stock.service.stock_scan_service import StockScanService
from module_stock.service.stock_strategy_service import StockStrategyService
from youw_test.strategies import load_strategy

# ---------------------------------------------------------------- metadata & vo


def test_stock_pool_rotation_metadata_is_portfolio() -> None:
    metadata = StockStrategyService._metadata(StockStrategyService._file('stock_pool_rotation'))

    assert metadata['is_portfolio'] is True
    assert metadata['category'] == 'rotation'


def test_run_request_accepts_optional_pool_name() -> None:
    request = StrategyRunRequest(strategyName='ma', code='000001', start='2024-01-01', end='2024-02-01')
    assert request.pool_name is None

    request_with_pool = StrategyRunRequest(
        strategyName='ma', code='000001', start='2024-01-01', end='2024-02-01', poolName='多因子池'
    )
    assert request_with_pool.pool_name == '多因子池'


def test_validate_request_requires_pool_name() -> None:
    with pytest.raises(ValidationError):
        StrategyValidateRequest(strategyName='stock_pool_rotation', code='000300', start='2023-01-01', end='2025-01-01')

    request = StrategyValidateRequest(
        strategyName='stock_pool_rotation', code='000300', start='2023-01-01', end='2025-01-01', poolName='多因子池'
    )
    assert request.pool_name == '多因子池'


def test_run_detail_includes_pool_name() -> None:
    run = SimpleNamespace(
        run_id='run-1', strategy_name='stock_pool_rotation', code='000300', start_date='2024-01-01',
        end_date='2024-02-01', initial_cash=100000, commission_rate='0.0003', stamp_tax_rate='0.001',
        benchmark_code='000300', pool_name='多因子池', strategy_params={}, status='success',
        progress=100, error_message=None, summary={}, curves=None, trades=[], run_logs=[], create_time=None,
    )

    detail = StockStrategyService._status_model(run, detail=True)
    assert detail.pool_name == '多因子池'


# ---------------------------------------------------------------- rolling validation helpers


def test_validation_windows_split_by_year() -> None:
    windows = StockStrategyService._validation_windows('2023-05-01', '2025-02-01')

    assert windows == [
        ('2023-05-01', '2023-12-31'),
        ('2024-01-01', '2024-12-31'),
        ('2025-01-01', '2025-02-01'),
    ]


def test_validation_windows_reject_short_span() -> None:
    assert StockStrategyService._validation_windows('2024-01-01', '2024-01-20') == []


def test_aggregate_validation_summary() -> None:
    windows = [
        {'status': 'success', 'summary': {'returnRate': 0.10, 'annualReturn': 0.2, 'sharpeRatio': 1.0, 'maxDrawdown': -0.05}},
        {'status': 'success', 'summary': {'returnRate': -0.05, 'annualReturn': -0.1, 'sharpeRatio': -0.5, 'maxDrawdown': -0.08}},
        {'status': 'failed', 'error': 'boom'},
    ]

    summary = StockStrategyService._aggregate_validation_summary(windows, total=3)

    assert summary['totalWindows'] == 3
    assert summary['successWindows'] == 2
    assert summary['failedWindows'] == 1
    assert summary['positiveWindows'] == 1
    assert summary['avgReturnRate'] == round((0.10 - 0.05) / 2, 6)
    assert summary['combinedReturnRate'] == round(1.10 * 0.95 - 1, 6)


# ---------------------------------------------------------------- scan portfolio mode


@pytest.mark.asyncio
async def test_run_scan_portfolio_strategy_runs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    created_batch = None
    created_items: list[Any] = []
    codes = [('000001', '平安银行'), ('600519', '贵州茅台')]

    async def fake_codes(db: Any, pool_name: str) -> list[tuple[str, str]]:
        return codes

    async def fake_create_batch(db: Any, batch: Any) -> Any:
        nonlocal created_batch
        created_batch = batch
        return batch

    async def fake_bulk_create(db: Any, items: list[Any]) -> None:
        created_items.extend(items)

    monkeypatch.setattr(
        'module_stock.service.stock_scan_service.StockStrategyService._file',
        staticmethod(lambda name: SimpleNamespace()),
    )
    monkeypatch.setattr(
        'module_stock.service.stock_scan_service.StockStrategyService._metadata',
        staticmethod(lambda path: {'is_portfolio': True}),
    )
    monkeypatch.setattr(StockPoolDao, 'codes_by_pool', fake_codes)
    monkeypatch.setattr(
        'module_stock.service.stock_scan_service.StockStrategyService._coerce_strategy_params',
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(StockScanDao, 'create_batch', fake_create_batch)
    monkeypatch.setattr(StockScanDao, 'bulk_create_items', fake_bulk_create)
    monkeypatch.setattr(StockScanService, '_execute_scan', AsyncMock(return_value=None))

    request = ScanRunRequestModel(strategyName='stock_pool_rotation', poolName='多因子池', start='2024-01-01', end='2024-02-01')
    batch_id = await StockScanService.run_scan(_FakeDb(), request)

    assert batch_id == created_batch.batch_id
    assert created_batch.total_count == 1
    assert created_batch.pool_codes == ['000001', '600519']
    assert len(created_items) == 1
    assert created_items[0].code == '000300'
    assert created_items[0].name == '组合回测（股票池）'


class _FakeDb:
    async def commit(self) -> None:
        pass


# ---------------------------------------------------------------- backtrader strategy behaviour


def _feed(name: str, closes: list[float]) -> bt.feeds.PandasData:
    index = pd.date_range('2024-01-01', periods=len(closes), freq='B')
    frame = pd.DataFrame(
        {'open': closes, 'high': closes, 'low': closes, 'close': closes, 'volume': [10000.0] * len(closes)},
        index=index,
    )
    return bt.feeds.PandasData(dataname=frame), name


def _run_rotation(stock_a: list[float], stock_b: list[float] | None = None, **params: Any) -> Any:
    strategy_cls = load_strategy('stock_pool_rotation')
    cerebro = bt.Cerebro()
    main_closes = [10.0 + 0.02 * i for i in range(max(len(stock_a), 30))]
    cerebro.adddata(_feed('000300', main_closes)[0], name='000300')
    cerebro.adddata(_feed('A', stock_a)[0], name='A')
    if stock_b is not None:
        cerebro.adddata(_feed('B', stock_b)[0], name='B')
    defaults = {'mom_period': 5, 'regime_ma_period': 10, 'top_n': 1, 'rotate_gain': 0.05, 'stop_ratio': 0.92, 'cooldown_days': 1}
    defaults.update(params)
    cerebro.addstrategy(strategy_cls, **defaults)
    cerebro.broker.setcash(1_000_000)

    class _Commission(bt.CommissionInfo):
        params = (('commission', 0.0), ('stamp_duty', 0.0), ('min_commission', 0.0))

        def _getcommission(self, size, price, pseudoexec) -> float:
            return 0.0

    cerebro.broker.addcommissioninfo(_Commission())
    results = cerebro.run()
    return results[0]


def test_rotation_buys_top_momentum_stock() -> None:
    rising = [10.0 + 0.2 * i for i in range(30)]
    flat = [10.0] * 30
    strategy = _run_rotation(rising, flat)

    assert strategy.getposition(strategy.datas[1]).size > 0
    assert strategy.getposition(strategy.datas[2]).size == 0


def test_rotation_stop_loss_triggers_cooldown() -> None:
    prices = [10.0] * 12 + [11.0] * 6 + [9.0] * 6
    strategy = _run_rotation(prices)

    sold = any(record['side'] == '卖出' for record in strategy.execution_records)
    assert sold
    assert strategy._cooldown.get('A') is not None
