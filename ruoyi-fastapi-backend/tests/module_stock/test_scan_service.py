"""批量回测选股（scan）服务单元测试。"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from exceptions.exception import ServiceException
from module_stock.dao.stock_pool_dao import StockPoolDao
from module_stock.dao.stock_scan_dao import StockScanDao
from module_stock.entity.vo.stock_paper_vo import ScanItemQueryModel, ScanRunRequestModel
from module_stock.service.stock_scan_service import StockScanService

CODES = [('000001', '平安银行'), ('600519', '贵州茅台'), ('300750', '宁德时代')]


class FakeDb:
    """模拟异步数据库会话，仅支持 commit。"""

    async def commit(self) -> None:
        pass

    def __aenter__(self) -> 'FakeDb':
        return self

    def __aexit__(self, *args: Any) -> None:
        pass


def test_scan_run_request_validates_pool_and_dates() -> None:
    request = ScanRunRequestModel(
        strategyName='ma', poolName='成长池', start='2024-01-01', end='2024-02-01'
    )
    assert request.pool_name == '成长池'
    assert request.initial_cash == 1_000_000

    with pytest.raises(ValidationError):
        ScanRunRequestModel(strategyName='ma', poolName='成长池', start='2024-02-01', end='2024-01-01')
    with pytest.raises(ValidationError):
        ScanRunRequestModel(strategyName='ma', poolName='成长池', start='2024-01-01', end='2024-01-01')


def test_scan_run_request_rejects_bad_benchmark_code() -> None:
    with pytest.raises(ValidationError):
        ScanRunRequestModel(strategyName='ma', poolName='成长池', start='2024-01-01', end='2024-02-01', benchmarkCode='abc')


def test_scan_item_query_sort_whitelist() -> None:
    query = ScanItemQueryModel(sortBy='sharpeRatio', order='asc')
    assert query.sort_by == 'sharpe_ratio'
    assert query.order == 'asc'

    with pytest.raises(ValidationError):
        ScanItemQueryModel(sortBy='error_message')
    with pytest.raises(ValidationError):
        ScanItemQueryModel(order='middle')


def test_scan_pick_request_dedupes_and_validates_codes() -> None:
    from module_stock.entity.vo.stock_paper_vo import ScanPickRequestModel

    request = ScanPickRequestModel(batchId='b1', codes=['600000', '600000', '000001'])
    assert request.codes == ['600000', '000001']

    with pytest.raises(ValidationError):
        ScanPickRequestModel(batchId='b1', codes=['60000'])
    with pytest.raises(ValidationError):
        ScanPickRequestModel(batchId='b1', codes=['60000A'])


@pytest.mark.asyncio
async def test_run_scan_creates_batch_and_items(monkeypatch: pytest.MonkeyPatch) -> None:
    created_batch = None
    created_items: list[Any] = []

    async def fake_codes(db: Any, pool_name: str) -> list[tuple[str, str]]:
        assert pool_name == '成长池'
        return CODES

    async def fake_create_batch(db: Any, batch: Any) -> Any:
        nonlocal created_batch
        created_batch = batch
        return batch

    async def fake_bulk_create(db: Any, items: list[Any]) -> None:
        created_items.extend(items)

    monkeypatch.setattr(StockScanService, '_file_strategy', None, raising=False)
    monkeypatch.setattr(
        'module_stock.service.stock_scan_service.StockStrategyService._file',
        staticmethod(lambda name: SimpleNamespace()),
    )
    monkeypatch.setattr(StockPoolDao, 'codes_by_pool', fake_codes)
    monkeypatch.setattr(
        'module_stock.service.stock_scan_service.StockStrategyService._coerce_strategy_params',
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(StockScanDao, 'create_batch', fake_create_batch)
    monkeypatch.setattr(StockScanDao, 'bulk_create_items', fake_bulk_create)
    # 阻止真正后台执行
    monkeypatch.setattr(
        StockScanService, '_execute_scan', AsyncMock(return_value=None)
    )

    request = ScanRunRequestModel(strategyName='ma', poolName='成长池', start='2024-01-01', end='2024-02-01')
    batch_id = await StockScanService.run_scan(FakeDb(), request)

    assert created_batch is not None
    assert created_batch.pool_name == '成长池'
    assert created_batch.total_count == 3
    assert len(created_items) == 3
    assert all(item.status == 'pending' for item in created_items)
    assert batch_id == created_batch.batch_id


@pytest.mark.asyncio
async def test_run_scan_rejects_empty_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_codes(db: Any, pool_name: str) -> list[tuple[str, str]]:
        return []

    monkeypatch.setattr(
        'module_stock.service.stock_scan_service.StockStrategyService._file',
        staticmethod(lambda name: SimpleNamespace()),
    )
    monkeypatch.setattr(StockPoolDao, 'codes_by_pool', fake_codes)
    request = ScanRunRequestModel(strategyName='ma', poolName='空池', start='2024-01-01', end='2024-02-01')

    with pytest.raises(ServiceException, match='不存在或为空'):
        await StockScanService.run_scan(FakeDb(), request)


@pytest.mark.asyncio
async def test_run_scan_rejects_invalid_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_file(name: str) -> Any:
        raise ServiceException(message='策略不存在')

    monkeypatch.setattr(
        'module_stock.service.stock_scan_service.StockStrategyService._file',
        staticmethod(fake_file),
    )
    request = ScanRunRequestModel(strategyName='not_exist', poolName='池', start='2024-01-01', end='2024-02-01')

    with pytest.raises(ServiceException):
        await StockScanService.run_scan(FakeDb(), request)


@pytest.mark.asyncio
async def test_execute_scan_marks_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [
        SimpleNamespace(id=1, code='000001', name='平安银行', status='pending'),
        SimpleNamespace(id=2, code='999999', name='异常股', status='pending'),
    ]
    batch = SimpleNamespace(
        batch_id='b1', strategy_name='ma', pool_name='池', start_date='2024-01-01', end_date='2024-02-01',
        initial_cash=1000000, commission_rate='0.0003', stamp_tax_rate='0.001',
        benchmark_code=None, strategy_params={},
    )
    updated_items: dict[int, str] = {}
    session_calls = 0

    def fake_session_factory(**kwargs: Any) -> FakeDb:
        nonlocal session_calls
        session_calls += 1
        return FakeDb()

    async def fake_get_batch(db: Any, batch_id: str) -> Any:
        return batch

    async def fake_get_items(db: Any, batch_id: str) -> list[Any]:
        return items

    async def fake_update_item(db: Any, item_id: int, **values: Any) -> None:
        if 'status' in values:
            updated_items[item_id] = values['status']

    async def fake_count(db: Any, batch_id: str) -> dict[str, int]:
        return {'success': 1, 'failed': 1}

    def fake_backtest(code: str, **kwargs: Any) -> dict[str, Any]:
        if code == '999999':
            raise RuntimeError('行情缺失')
        return {'summary': {'returnRate': 0.1, 'annualReturn': 0.2, 'sharpeRatio': 1.0, 'maxDrawdown': -0.05, 'winRate': 0.6, 'profitLossRatio': 1.5, 'tradeCount': 5}}

    monkeypatch.setattr(
        'module_stock.service.stock_scan_service.DataSourceRegistry.session',
        staticmethod(fake_session_factory),
    )
    monkeypatch.setattr(StockScanDao, 'get_batch', fake_get_batch)
    monkeypatch.setattr(StockScanDao, 'get_items_by_batch', fake_get_items)
    monkeypatch.setattr(StockScanDao, 'update_batch', AsyncMock())
    monkeypatch.setattr(StockScanDao, 'update_item', fake_update_item)
    monkeypatch.setattr(StockScanDao, 'count_items_by_status', fake_count)
    monkeypatch.setattr(
        'module_stock.service.stock_scan_service.StockStrategyService.backtest_once',
        staticmethod(fake_backtest),
    )

    await StockScanService._execute_scan('b1')

    assert updated_items[1] == 'success'
    assert updated_items[2] == 'failed'


@pytest.mark.asyncio
async def test_list_items_requires_existing_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_batch(db: Any, batch_id: str) -> Any:
        if batch_id == 'exists':
            return SimpleNamespace(batch_id='exists')
        return None

    monkeypatch.setattr(StockScanDao, 'get_batch', fake_get_batch)
    monkeypatch.setattr(StockScanDao, 'list_items', AsyncMock(return_value=SimpleNamespace(rows=[])))

    result = await StockScanService.list_items(FakeDb(), 'exists', ScanItemQueryModel())
    assert result is not None

    with pytest.raises(ServiceException, match='不存在'):
        await StockScanService.list_items(FakeDb(), 'missing', ScanItemQueryModel())
