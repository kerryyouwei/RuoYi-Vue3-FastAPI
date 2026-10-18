"""模拟交易（paper）服务单元测试。"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from exceptions.exception import ServiceException
from module_stock.dao.stock_paper_dao import StockPaperDao
from module_stock.dao.stock_pool_dao import StockPoolDao
from module_stock.dao.stock_scan_dao import StockScanDao
from module_stock.entity.vo.stock_paper_vo import (
    PaperAccountInitRequestModel,
    PaperUniverseAddRequestModel,
    PaperUniverseRemoveRequestModel,
)
from module_stock.service import stock_paper_service as paper_service_module
from module_stock.service.stock_paper_service import (
    COMMISSION_RATE,
    DEFAULT_ACCOUNT_NAME,
    MIN_COMMISSION,
    STAMP_TAX_RATE,
    StockPaperService,
)
from module_stock.service.stock_realtime_service import StockRealtimeService


class FakeDb:
    async def commit(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        return None

    def __aenter__(self) -> 'FakeDb':
        return self

    def __aexit__(self, *args: Any) -> None:
        pass


def _make_account(**changes: Any) -> SimpleNamespace:
    defaults = {
        'id': 1, 'account_name': DEFAULT_ACCOUNT_NAME, 'strategy_name': 'ma',
        'initial_cash': 1_000_000, 'cash': 1_000_000.0, 'status': 'active',
    }
    defaults.update(changes)
    return SimpleNamespace(**defaults)


def _make_position(**changes: Any) -> SimpleNamespace:
    defaults = {
        'id': 10, 'account_id': 1, 'code': '000001', 'name': '平安银行',
        'quantity': 1000, 'available_quantity': 1000, 'avg_cost': 10.0, 'last_price': 11.0,
    }
    defaults.update(changes)
    return SimpleNamespace(**defaults)


def test_paper_init_request_dedupes_codes() -> None:
    request = PaperAccountInitRequestModel(
        accountName='default', strategyName='ma', initialCash=1_000_000,
        codes=['000001', '000001', '600519'],
    )
    assert request.codes == ['000001', '600519']

    with pytest.raises(ValidationError):
        PaperAccountInitRequestModel(strategyName='ma', codes=['ABC'])
    # codes 为空合法：保留现有标的池，仅重置资金与交易记录
    assert PaperAccountInitRequestModel(strategyName='ma').codes == []


@pytest.mark.asyncio
async def test_init_account_resets_and_rewrites_universe(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _make_account()
    created_universes: list[Any] = []
    deactivated: list[set[str]] = []
    deleted = {'positions': 0, 'orders': 0, 'signals': 0, 'snapshots': 0}
    updated_account: dict[str, Any] = {}

    async def fake_get_account(db: Any, name: str) -> Any:
        return account if name == DEFAULT_ACCOUNT_NAME else None

    async def fake_update_account(db: Any, account_id: int, **values: Any) -> None:
        updated_account.update(values)

    async def fake_delete(kind: str) -> AsyncMock:
        return AsyncMock(side_effect=lambda db, account_id: None)

    async def fake_delete_positions(db: Any, account_id: int) -> None:
        deleted['positions'] += 1

    async def fake_delete_orders(db: Any, account_id: int) -> None:
        deleted['orders'] += 1

    async def fake_delete_signals(db: Any, account_id: int) -> None:
        deleted['signals'] += 1

    async def fake_delete_snapshots(db: Any, account_id: int) -> None:
        deleted['snapshots'] += 1

    async def fake_get_universe(db: Any, account_id: int) -> list[Any]:
        return []

    async def fake_get_universe_by_code(db: Any, account_id: int, code: str) -> Any:
        return None

    async def fake_add_universe(db: Any, universe: Any) -> Any:
        created_universes.append(universe)
        return universe

    async def fake_deactivate(db: Any, account_id: int, codes: set[str], skip_held: set[str] | None = None) -> None:
        deactivated.append((codes, skip_held))

    async def fake_get_held_codes(db: Any, account_id: int) -> set[str]:
        return set()

    async def fake_add_universe_log(db: Any, log: Any) -> Any:
        return log

    monkeypatch.setattr(
        'module_stock.service.stock_paper_service.StockStrategyService._file',
        staticmethod(lambda name: SimpleNamespace()),
    )
    monkeypatch.setattr(StockPaperDao, 'get_account', fake_get_account)
    monkeypatch.setattr(StockPaperDao, 'update_account', fake_update_account)
    monkeypatch.setattr(StockPaperDao, 'delete_positions_by_account', fake_delete_positions)
    monkeypatch.setattr(StockPaperDao, 'delete_orders_by_account', fake_delete_orders)
    monkeypatch.setattr(StockPaperDao, 'delete_signals_by_account', fake_delete_signals)
    monkeypatch.setattr(StockPaperDao, 'delete_snapshots_by_account', fake_delete_snapshots)
    monkeypatch.setattr(StockPaperDao, 'get_universe', fake_get_universe)
    monkeypatch.setattr(StockPaperDao, 'get_universe_by_code', fake_get_universe_by_code)
    monkeypatch.setattr(StockPaperDao, 'add_universe', fake_add_universe)
    monkeypatch.setattr(StockPaperDao, 'deactivate_universe_except', fake_deactivate)
    monkeypatch.setattr(StockPaperDao, 'get_held_codes', fake_get_held_codes)
    monkeypatch.setattr(StockPaperDao, 'add_universe_log', fake_add_universe_log)

    request = PaperAccountInitRequestModel(
        strategyName='ma', initialCash=500000, codes=['000001', '600519', '000001'],
    )
    result = await StockPaperService.init_account(FakeDb(), request)

    assert result['addedCount'] == 2
    # 请求模型层已对 codes 去重，服务层不会出现重复输入
    assert result['skippedCount'] == 0
    assert account.cash == 500000.0
    assert updated_account['initial_cash'] == 500000
    assert deleted == {'positions': 1, 'orders': 1, 'signals': 1, 'snapshots': 1}
    assert {u.code for u in created_universes} == {'000001', '600519'}
    # 默认非 replace：不再全量停用既有标的池
    assert deactivated == []


@pytest.mark.asyncio
async def test_init_account_replace_deactivates_except_held(monkeypatch: pytest.MonkeyPatch) -> None:
    """replace=true 时全量重置标的池，但持仓中的标的不会被停用。"""
    account = _make_account()

    async def fake_get_account(db: Any, name: str) -> Any:
        return account

    async def fake_get_held_codes(db: Any, account_id: int) -> set[str]:
        return {'600519'}

    deactivated: list[tuple[set[str], set[str] | None]] = []

    async def fake_deactivate(db: Any, account_id: int, codes: set[str], skip_held: set[str] | None = None) -> None:
        deactivated.append((codes, skip_held))

    async def fake_noop(db: Any, account_id: int) -> None:
        return None

    async def fake_get_universe_by_code(db: Any, account_id: int, code: str) -> Any:
        return None

    async def fake_add_universe(db: Any, universe: Any) -> Any:
        return universe

    async def fake_add_universe_log(db: Any, log: Any) -> Any:
        return log

    monkeypatch.setattr(
        'module_stock.service.stock_paper_service.StockStrategyService._file',
        staticmethod(lambda name: SimpleNamespace()),
    )
    async def fake_update_account(db: Any, account_id: int, **values: Any) -> None:
        return None

    monkeypatch.setattr(StockPaperDao, 'get_account', fake_get_account)
    monkeypatch.setattr(StockPaperDao, 'update_account', fake_update_account)
    monkeypatch.setattr(StockPaperDao, 'delete_positions_by_account', fake_noop)
    monkeypatch.setattr(StockPaperDao, 'delete_orders_by_account', fake_noop)
    monkeypatch.setattr(StockPaperDao, 'delete_signals_by_account', fake_noop)
    monkeypatch.setattr(StockPaperDao, 'delete_snapshots_by_account', fake_noop)
    monkeypatch.setattr(StockPaperDao, 'get_held_codes', fake_get_held_codes)
    monkeypatch.setattr(StockPaperDao, 'get_universe_by_code', fake_get_universe_by_code)
    monkeypatch.setattr(StockPaperDao, 'add_universe', fake_add_universe)
    monkeypatch.setattr(StockPaperDao, 'deactivate_universe_except', fake_deactivate)
    monkeypatch.setattr(StockPaperDao, 'add_universe_log', fake_add_universe_log)

    request = PaperAccountInitRequestModel(
        strategyName='ma', codes=['000001', '600519'], replace=True,
    )
    await StockPaperService.init_account(FakeDb(), request)

    assert deactivated == [({'000001', '600519'}, {'600519'})]


@pytest.mark.asyncio
async def test_init_account_rejects_invalid_strategy() -> None:
    def fake_file(name: str) -> Any:
        raise ServiceException(message='策略不存在')

    request = PaperAccountInitRequestModel(strategyName='no_such', codes=['000001'])
    with pytest.raises(ServiceException):
        await StockPaperService.init_account(FakeDb(), request)


@pytest.mark.asyncio
async def test_get_account_computes_equity(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _make_account(cash=500000.0)
    positions = [
        _make_position(code='000001', quantity=1000, avg_cost=10.0, last_price=12.0),
        _make_position(code='600519', quantity=200, avg_cost=50.0, last_price=45.0),
    ]

    async def fake_get_account(db: Any, name: str) -> Any:
        return account

    async def fake_list_positions(db: Any, account_id: int) -> list[Any]:
        return positions

    async def fake_refresh_position_prices(db: Any, positions: list[Any]) -> None:
        return None

    monkeypatch.setattr(StockPaperDao, 'get_account', fake_get_account)
    monkeypatch.setattr(StockPaperDao, 'list_positions', fake_list_positions)
    monkeypatch.setattr(StockPaperService, '_refresh_position_prices', fake_refresh_position_prices)

    result = await StockPaperService.get_account(FakeDb())
    assert result.position_value == 1000 * 12 + 200 * 45
    assert result.total_equity == 500000 + result.position_value
    assert result.pnl == result.total_equity - 1_000_000
    assert abs(result.return_rate - result.pnl / 1_000_000) < 1e-12


@pytest.mark.asyncio
async def test_get_account_requires_initialization(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_account(db: Any, name: str) -> Any:
        return None

    monkeypatch.setattr(StockPaperDao, 'get_account', fake_get_account)
    with pytest.raises(ServiceException) as exc_info:
        await StockPaperService.get_account(FakeDb())
    assert exc_info.value.message and '尚未初始化' in exc_info.value.message


@pytest.mark.asyncio
async def test_execute_buy_lot_sizing_and_cash_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """等权分仓100股取整 + 现金校验。"""
    account = _make_account(cash=50_000.0, initial_cash=1_000_000)
    signal = SimpleNamespace(id=100, account_id=1, code='000001', name='平安银行', signal_date='2024-01-01', execute_date='2024-01-02', signal='买入')
    positions: dict[str, Any] = {}
    created_orders: list[Any] = []
    updated_signal_status: dict[int, str] = {}

    async def fake_update_account(db: Any, account_id: int, **values: Any) -> None:
        pass

    async def fake_create_position(db: Any, position: Any) -> Any:
        return position

    async def fake_create_order(db: Any, order: Any) -> Any:
        created_orders.append(order)
        return order

    async def fake_update_signal(db: Any, signal_id: int, **values: Any) -> None:
        if 'status' in values:
            updated_signal_status[signal_id] = values['status']

    async def fake_mark_skipped(db: Any, account_id: int, sig: Any, name: Any, price: Any, reason: str) -> None:
        updated_signal_status[sig.id] = 'skipped'

    async def fake_get_position_by_code(db: Any, account_id: int, code: str) -> Any:
        return None

    monkeypatch.setattr(StockPaperDao, 'update_account', fake_update_account)
    monkeypatch.setattr(StockPaperDao, 'create_position', fake_create_position)
    monkeypatch.setattr(StockPaperDao, 'create_order', fake_create_order)
    monkeypatch.setattr(StockPaperDao, 'update_signal', fake_update_signal)
    monkeypatch.setattr(StockPaperDao, 'get_position_by_code', fake_get_position_by_code)
    monkeypatch.setattr(StockPaperService, '_mark_skipped', fake_mark_skipped)

    # 等权 target=100000/1=100000, price=10, lot=100股 -> quantity=10000, amount=100000 > cash=50000 -> skip
    await StockPaperService._execute_buy(FakeDb(), account, signal, '平安银行', positions, 100000.0, 1, 10.0)
    assert updated_signal_status[100] == 'skipped'
    assert not created_orders

    # 充足资金: quantity = int(100000/10//100*100) = 10000, cost=100000+30=100030 <= 500000
    account2 = _make_account(cash=500_000.0, initial_cash=1_000_000)
    positions2: dict[str, Any] = {}
    created_orders2: list[Any] = []
    updated2: dict[int, str] = {}

    async def fake_create_order2(db: Any, order: Any) -> Any:
        created_orders2.append(order)
        return order

    async def fake_update_signal2(db: Any, signal_id: int, **values: Any) -> None:
        if 'status' in values:
            updated2[signal_id] = values['status']

    monkeypatch.setattr(StockPaperDao, 'create_order', fake_create_order2)
    monkeypatch.setattr(StockPaperDao, 'update_signal', fake_update_signal2)
    monkeypatch.setattr(StockPaperDao, 'get_position_by_code', fake_get_position_by_code)
    monkeypatch.setattr(StockPaperService, '_mark_skipped', fake_mark_skipped)

    await StockPaperService._execute_buy(FakeDb(), account2, signal, '平安银行', positions2, 100_000.0, 1, 10.0)
    assert updated2[100] == 'executed'
    assert len(created_orders2) == 1
    order = created_orders2[0]
    assert order.quantity == 10_000
    assert order.amount == 100_000.0
    assert abs(order.commission - max(100_000 * COMMISSION_RATE, MIN_COMMISSION)) < 1e-6


@pytest.mark.asyncio
async def test_execute_sell_t_plus_1_and_fees(monkeypatch: pytest.MonkeyPatch) -> None:
    """T+1 available=0 时跳过; 有持仓时全卖并扣佣金+印花税。"""
    account = _make_account(cash=0.0, initial_cash=1_000_000)
    signal = SimpleNamespace(id=200, account_id=1, code='000001', name='平安银行', signal_date='2024-01-01', execute_date='2024-01-02', signal='卖出')

    # available=0 -> skip
    position = _make_position(available_quantity=0)
    positions = {'000001': position}
    skipped_calls: list[str] = []

    async def fake_mark_skipped(db: Any, account_id: int, sig: Any, name: Any, price: Any, reason: str) -> None:
        skipped_calls.append(reason)

    async def fake_get_position_by_code(db: Any, account_id: int, code: str) -> Any:
        return None

    monkeypatch.setattr(StockPaperService, '_mark_skipped', fake_mark_skipped)
    monkeypatch.setattr(StockPaperDao, 'get_position_by_code', fake_get_position_by_code)
    await StockPaperService._execute_sell(FakeDb(), account, signal, '平安银行', positions, 12.0)
    assert len(skipped_calls) == 1
    assert 'T+1' in skipped_calls[0] or '可卖' in skipped_calls[0]

    # available=1000 -> sell all
    position2 = _make_position(available_quantity=1000, quantity=1000)
    positions2 = {'000001': position2}
    created_orders: list[Any] = []

    async def fake_create_order(db: Any, order: Any) -> Any:
        created_orders.append(order)
        return order

    async def fake_delete_positions(db: Any, account_id: int, code: str) -> None:
        positions2.pop(code, None)

    async def fake_update_signal(db: Any, signal_id: int, **values: Any) -> None:
        pass

    async def fake_get_db_position(db: Any, account_id: int, code: str) -> Any:
        return positions2.get(code)

    monkeypatch.setattr(StockPaperDao, 'create_order', fake_create_order)
    monkeypatch.setattr(StockPaperDao, 'delete_positions_by_code', fake_delete_positions)
    monkeypatch.setattr(StockPaperDao, 'update_signal', fake_update_signal)
    monkeypatch.setattr(StockPaperDao, 'update_account', AsyncMock())
    monkeypatch.setattr(StockPaperDao, 'get_position_by_code', fake_get_db_position)
    monkeypatch.setattr(StockPaperService, '_mark_skipped', fake_mark_skipped)

    await StockPaperService._execute_sell(FakeDb(), account, signal, '平安银行', positions2, 12.0)
    assert len(created_orders) == 1
    order = created_orders[0]
    assert order.quantity == 1000
    assert order.amount == 12_000.0
    assert abs(order.stamp_tax - 12_000 * STAMP_TAX_RATE) < 1e-6
    assert '000001' not in positions2  # 全卖后删除持仓


@pytest.mark.asyncio
async def test_execute_buy_already_holding_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """已有持仓不再加仓。"""
    account = _make_account()
    signal = SimpleNamespace(id=300, account_id=1, code='000001', signal='买入', signal_date='2024-01-01', execute_date='2024-01-02')
    position = _make_position()
    positions = {'000001': position}
    skipped_calls: list[str] = []

    async def fake_mark_skipped(db: Any, account_id: int, sig: Any, name: Any, price: Any, reason: str) -> None:
        skipped_calls.append(reason)

    monkeypatch.setattr(StockPaperService, '_mark_skipped', fake_mark_skipped)
    await StockPaperService._execute_buy(FakeDb(), account, signal, '平安银行', positions, 100_000.0, 1, 10.0)
    assert len(skipped_calls) == 1
    assert '加仓' in skipped_calls[0]


@pytest.mark.asyncio
async def test_pick_to_universe(monkeypatch: pytest.MonkeyPatch) -> None:
    batch = SimpleNamespace(batch_id='b1', strategy_name='ma', initial_cash=1_000_000)
    items = [SimpleNamespace(code='000001', name='平安银行')]
    account = _make_account()
    created: list[Any] = []
    existing_universe: dict[str, Any] = {}

    async def fake_get_batch(db: Any, batch_id: str) -> Any:
        return batch if batch_id == 'b1' else None

    async def fake_get_items_for_codes(db: Any, batch_id: str, codes: list[str]) -> list[Any]:
        return [i for i in items if i.code in codes]

    async def fake_ensure(db: Any, strategy_name: str, initial_cash: int, account_name: str) -> Any:
        return account

    async def fake_get_universe_by_code(db: Any, account_id: int, code: str) -> Any:
        return existing_universe.get(code)

    async def fake_add(db: Any, universe: Any) -> Any:
        created.append(universe)
        existing_universe[universe.code] = universe
        return universe

    async def fake_update(db: Any, account_id: int, code: str, **values: Any) -> None:
        existing_universe[code] = SimpleNamespace(code=code, status='active', **values)

    async def fake_add_universe_log(db: Any, log: Any) -> Any:
        return log

    monkeypatch.setattr(StockScanDao, 'get_batch', fake_get_batch)
    monkeypatch.setattr(StockScanDao, 'get_items_for_codes', fake_get_items_for_codes)
    monkeypatch.setattr(StockPaperService, 'ensure_account', fake_ensure)
    monkeypatch.setattr(StockPaperDao, 'get_universe_by_code', fake_get_universe_by_code)
    monkeypatch.setattr(StockPaperDao, 'add_universe', fake_add)
    monkeypatch.setattr(StockPaperDao, 'update_universe_by_code', fake_update)
    monkeypatch.setattr(StockPaperDao, 'add_universe_log', fake_add_universe_log)

    result = await StockPaperService.pick_to_universe(FakeDb(), 'b1', ['000001', '600519'])
    assert result['addedCount'] == 2
    assert result['skippedCount'] == 0

    # 重复加入已存在的 -> skip
    result2 = await StockPaperService.pick_to_universe(FakeDb(), 'b1', ['000001'])
    assert result2['addedCount'] == 0
    assert result2['skippedCount'] == 1


@pytest.mark.asyncio
async def test_list_positions_refreshes_stale_last_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """持仓最新价应取自实时行情而非数据库缓存价。"""
    account = _make_account()
    position = _make_position(code='603127', quantity=6400, avg_cost=51.48, last_price=48.79)
    positions = [position]

    async def fake_get_account(db: Any, name: str) -> Any:
        return account

    async def fake_list_positions(db: Any, account_id: int) -> list[Any]:
        return positions

    async def fake_fetch_realtime(codes: list[str]) -> list[dict[str, Any]]:
        return [{'code': '603127', 'price': 50.65, 'volume': 1000.0, 'snapshot_time': '2026-10-15T10:31:00'}]

    async def fake_update_position(db: Any, position_id: int, **values: Any) -> None:
        update_calls.append((position_id, values))

    update_calls: list[tuple[int, dict[str, Any]]] = []
    paper_service_module._realtime_quote_cache.clear()
    monkeypatch.setattr(StockPaperDao, 'get_account', fake_get_account)
    monkeypatch.setattr(StockPaperDao, 'list_positions', fake_list_positions)
    monkeypatch.setattr(StockPaperDao, 'update_position', fake_update_position)
    monkeypatch.setattr(StockRealtimeService, 'fetch_realtime', fake_fetch_realtime)

    result = await StockPaperService.list_positions(FakeDb())
    assert len(result) == 1
    assert result[0].last_price == 50.65
    assert result[0].market_value == 6400 * 50.65
    assert result[0].pnl == pytest.approx(6400 * (50.65 - 51.48))
    assert update_calls and any('last_price' in v for _, v in update_calls)


@pytest.mark.asyncio
async def test_refresh_position_prices_keeps_cache_on_empty_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    """行情源无返回时保留数据库缓存价。"""
    position = _make_position(code='603127', quantity=6400, avg_cost=51.48, last_price=48.79)
    positions = [position]

    async def fake_fetch_realtime_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
        return {}

    async def fake_update_position(db: Any, position_id: int, **values: Any) -> None:
        raise AssertionError('无有效行情时不应更新持仓价')

    monkeypatch.setattr(StockPaperService, '_fetch_realtime_quotes_cached', fake_fetch_realtime_quotes)
    monkeypatch.setattr(StockPaperDao, 'update_position', fake_update_position)

    await StockPaperService._refresh_position_prices(FakeDb(), positions)
    assert position.last_price == 48.79


# ---------------------------------------------------------------- 标的池动态增删


def _make_universe(**changes: Any) -> SimpleNamespace:
    defaults = {
        'id': 100, 'account_id': 1, 'code': '600519', 'name': '贵州茅台',
        'source_batch_id': None, 'source_type': 'manual', 'status': 'active',
    }
    defaults.update(changes)
    return SimpleNamespace(**defaults)


def _patch_universe_daos(
    monkeypatch: pytest.MonkeyPatch,
    account: Any,
    store: dict[str, Any],
    logs: list[Any],
    held_codes: set[str] | None = None,
) -> None:
    async def fake_get_account(db: Any, name: str) -> Any:
        return account if name == account.account_name else None

    async def fake_codes_by_pool(db: Any, pool_name: str) -> list[tuple[str, str | None]]:
        if pool_name == 'mf_pool':
            return [('600519', '贵州茅台'), ('000001', '平安银行')]
        return []

    async def fake_get_universe_by_code(db: Any, account_id: int, code: str) -> Any:
        return store.get(code)

    async def fake_add_universe(db: Any, universe: Any) -> Any:
        store[universe.code] = universe
        return universe

    async def fake_update_universe_by_code(db: Any, account_id: int, code: str, **values: Any) -> None:
        current = store.get(code) or SimpleNamespace(code=code)
        for key, value in values.items():
            setattr(current, key, value)
        store[code] = current

    async def fake_deactivate_universe_codes(db: Any, account_id: int, codes: Any) -> None:
        for code in codes:
            if code in store:
                store[code].status = 'inactive'

    async def fake_add_universe_log(db: Any, log: Any) -> Any:
        logs.append(log)
        return log

    async def fake_get_held_codes(db: Any, account_id: int) -> set[str]:
        return held_codes or set()

    monkeypatch.setattr(StockPaperDao, 'get_account', fake_get_account)
    monkeypatch.setattr(StockPoolDao, 'codes_by_pool', fake_codes_by_pool)
    monkeypatch.setattr(StockPaperDao, 'get_universe_by_code', fake_get_universe_by_code)
    monkeypatch.setattr(StockPaperDao, 'add_universe', fake_add_universe)
    monkeypatch.setattr(StockPaperDao, 'update_universe_by_code', fake_update_universe_by_code)
    monkeypatch.setattr(StockPaperDao, 'deactivate_universe_codes', fake_deactivate_universe_codes)
    monkeypatch.setattr(StockPaperDao, 'add_universe_log', fake_add_universe_log)
    monkeypatch.setattr(StockPaperDao, 'get_held_codes', fake_get_held_codes)


@pytest.mark.asyncio
async def test_add_to_universe_whole_pool_and_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    """整池加入写入 pool 来源与池名简称；重复加入幂等跳过；手工代码走 manual 来源并补名。"""
    account = _make_account()
    store: dict[str, Any] = {}
    logs: list[Any] = []
    _patch_universe_daos(monkeypatch, account, store, logs)

    result = await StockPaperService.add_to_universe(FakeDb(), PaperUniverseAddRequestModel(poolName='mf_pool'))
    assert result['addedCount'] == 2
    assert result['skippedCount'] == 0
    assert store['600519'].source_type == 'pool'
    assert store['600519'].source_batch_id == 'pool:mf_pool'
    assert store['600519'].name == '贵州茅台'
    assert len(logs) == 2
    assert all(log.action == 'add' and log.source_type == 'pool' for log in logs)

    result2 = await StockPaperService.add_to_universe(FakeDb(), PaperUniverseAddRequestModel(poolName='mf_pool'))
    assert result2['addedCount'] == 0
    assert result2['skippedCount'] == 2
    assert len(logs) == 2

    monkeypatch.setattr(
        StockPaperService, '_stock_names_from_mongo', staticmethod(lambda codes: {'300750': '宁德时代'})
    )
    result3 = await StockPaperService.add_to_universe(FakeDb(), PaperUniverseAddRequestModel(codes=['300750']))
    assert result3['addedCount'] == 1
    assert store['300750'].source_type == 'manual'
    assert store['300750'].name == '宁德时代'


@pytest.mark.asyncio
async def test_add_to_universe_pool_codes_pick_and_reactivate(monkeypatch: pytest.MonkeyPatch) -> None:
    """从原始池勾选加入；已 inactive 的标的重新激活并覆盖来源。"""
    account = _make_account()
    store: dict[str, Any] = {'600519': _make_universe(status='inactive', source_type='manual')}
    logs: list[Any] = []
    _patch_universe_daos(monkeypatch, account, store, logs)

    request = PaperUniverseAddRequestModel(poolName='mf_pool', poolCodes=['600519', '000001'])
    result = await StockPaperService.add_to_universe(FakeDb(), request)
    assert result['addedCount'] == 2
    assert result['skippedCount'] == 0
    assert store['600519'].status == 'active'
    assert store['600519'].source_type == 'pool'
    assert store['000001'].name == '平安银行'


@pytest.mark.asyncio
async def test_add_to_universe_validations(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _make_account()
    store: dict[str, Any] = {}
    logs: list[Any] = []
    _patch_universe_daos(monkeypatch, account, store, logs)

    async def _expect_add_error(request: Any, keyword: str) -> None:
        with pytest.raises(ServiceException) as exc_info:
            await StockPaperService.add_to_universe(FakeDb(), request)
        assert exc_info.value.message and keyword in exc_info.value.message

    await _expect_add_error(PaperUniverseAddRequestModel(poolCodes=['600519']), '同时提供')
    await _expect_add_error(PaperUniverseAddRequestModel(poolName='empty_pool'), '不存在或为空')
    await _expect_add_error(
        PaperUniverseAddRequestModel(poolName='mf_pool', poolCodes=['999999']), '不在股票池'
    )
    await _expect_add_error(PaperUniverseAddRequestModel(), '三选一')
    assert not store
    assert not logs


@pytest.mark.asyncio
async def test_remove_from_universe_held_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    """任一请求标的持仓中 → 整体拒绝且不做任何修改。"""
    account = _make_account()
    store: dict[str, Any] = {
        '000001': _make_universe(code='000001', name='平安银行'),
        '600519': _make_universe(),
    }
    logs: list[Any] = []
    deactivated: list[Any] = []

    async def fake_deactivate(db: Any, account_id: int, codes: Any) -> None:
        deactivated.append(list(codes))

    _patch_universe_daos(monkeypatch, account, store, logs, held_codes={'000001'})
    monkeypatch.setattr(StockPaperDao, 'deactivate_universe_codes', fake_deactivate)

    with pytest.raises(ServiceException) as exc_info:
        await StockPaperService.remove_from_universe(
            FakeDb(), PaperUniverseRemoveRequestModel(codes=['000001', '600519'])
        )
    assert exc_info.value.message and '持仓中' in exc_info.value.message
    assert '000001' in exc_info.value.message
    assert not deactivated
    assert not logs
    assert store['600519'].status == 'active'


@pytest.mark.asyncio
async def test_remove_from_universe_success_and_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """仅移出 active 标的并写日志；已移出/池外标的触发整体报错。"""
    account = _make_account()
    store: dict[str, Any] = {
        '000001': _make_universe(code='000001', name='平安银行'),
        '600519': _make_universe(status='inactive'),
    }
    logs: list[Any] = []
    _patch_universe_daos(monkeypatch, account, store, logs)

    result = await StockPaperService.remove_from_universe(
        FakeDb(), PaperUniverseRemoveRequestModel(codes=['000001', '600519', '300999'])
    )
    assert result['removedCount'] == 1
    assert store['000001'].status == 'inactive'
    assert len(logs) == 1
    assert logs[0].action == 'remove'
    assert logs[0].source_type == 'api'

    with pytest.raises(ServiceException) as exc_info:
        await StockPaperService.remove_from_universe(
            FakeDb(), PaperUniverseRemoveRequestModel(codes=['600519'])
        )
    assert exc_info.value.message and '均不在当前标的池' in exc_info.value.message
