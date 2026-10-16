"""飞书交易信号通知单元测试。"""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from config.database import DataSourceRegistry
from config.env import FeishuNotifyConfig
from module_stock.dao.stock_paper_dao import StockPaperDao
from module_stock.service.stock_feishu_notification_service import (
    FeishuNotificationService,
    FeishuRecallResult,
    FeishuSendResult,
    FeishuSignal,
)
from module_stock.service.stock_paper_service import StockPaperService
from module_stock.service.stock_realtime_service import StockRealtimeService
from module_stock.service.stock_signal_service import StockSignalService


class FakeResponse:
    def __init__(self, body: dict[str, Any], status_code: int = 200) -> None:
        self.body = body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.body


class FakeDb:
    def __init__(self) -> None:
        self.committed = 0
        self.flushed = 0
        self.added: list[Any] = []

    def add(self, item: Any) -> None:
        self.added.append(item)

    async def commit(self) -> None:
        self.committed += 1

    async def flush(self) -> None:
        self.flushed += 1

    def __aenter__(self) -> 'FakeDb':
        return self

    def __aexit__(self, *args: Any) -> None:
        return None


def _install_client(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any] | None = None, error: Exception | None = None
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, timeout: Any = None) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> 'FakeAsyncClient':
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any]) -> FakeResponse:
            requests.append({'url': url, 'json': json})
            if error is not None:
                raise error
            return FakeResponse(response or {})

    monkeypatch.setattr(httpx, 'AsyncClient', FakeAsyncClient)
    return requests


@pytest.mark.asyncio
async def test_send_text_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_enabled', False)

    def fail_client(*args: Any, **kwargs: Any) -> None:
        raise AssertionError('禁用状态不应创建HTTP客户端')

    monkeypatch.setattr(httpx, 'AsyncClient', fail_client)
    assert await FeishuNotificationService.send_text('测试消息') is False


@pytest.mark.asyncio
async def test_send_text_success_with_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_enabled', True)
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_mode', 'webhook')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_webhook_url', 'https://open.feishu.cn/hook/test')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_secret', 'secret')
    monkeypatch.setattr(FeishuNotificationService, '_build_sign', staticmethod(lambda timestamp, secret: 'signed'))
    requests = _install_client(monkeypatch, response={'code': 0})

    assert await FeishuNotificationService.send_text('测试消息') is True
    assert len(requests) == 1
    payload = requests[0]['json']
    assert payload['msg_type'] == 'text'
    assert payload['content']['text'] == '测试消息'
    assert payload['sign'] == 'signed'
    assert isinstance(payload['timestamp'], int)


@pytest.mark.asyncio
async def test_send_text_returns_false_when_feishu_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_enabled', True)
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_mode', 'webhook')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_webhook_url', 'https://open.feishu.cn/hook/test')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_secret', '')
    requests = _install_client(monkeypatch, response={'code': 19021, 'msg': 'invalid'})

    assert await FeishuNotificationService.send_text('测试消息') is False
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_send_text_returns_false_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_enabled', True)
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_mode', 'webhook')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_webhook_url', 'https://open.feishu.cn/hook/test')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_secret', '')
    _install_client(monkeypatch, error=httpx.ConnectError('network unavailable'))

    assert await FeishuNotificationService.send_text('测试消息') is False


@pytest.mark.asyncio
async def test_send_signal_formats_price_reason_and_time(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    async def fake_send_text_with_receipt(text: str) -> FeishuSendResult:
        captured.append(text)
        return FeishuSendResult(True, 'om_test')

    monkeypatch.setattr(FeishuNotificationService, 'send_text_with_receipt', staticmethod(fake_send_text_with_receipt))
    result = await FeishuNotificationService.send_signal(
        FeishuSignal(
            code='600000', name='示例股份', signal='买入', price=12.34, reason='MA5 上穿 MA20', time='10:31:00'
        )
    )

    assert result is True
    assert '【模拟交易信号】' in captured[0]
    assert '股票：600000 示例股份' in captured[0]
    assert '信号：买入' in captured[0]
    assert '现价：12.34' in captured[0]
    assert '原因：MA5 上穿 MA20' in captured[0]
    assert '时间：10:31:00' in captured[0]


@pytest.mark.asyncio
async def test_send_signal_summary_includes_all_directions(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    async def fake_send_text_with_receipt(text: str) -> FeishuSendResult:
        captured.append(text)
        return FeishuSendResult(True, 'om_test')

    monkeypatch.setattr(FeishuNotificationService, 'send_text_with_receipt', staticmethod(fake_send_text_with_receipt))
    signals = [
        FeishuSignal(code='600000', name='示例股份', signal='买入', price=12.34, reason='MA5 上穿 MA20'),
        FeishuSignal(code='000001', name='示例银行', signal='卖出', price=8.90, reason='MA5 下穿 MA20'),
        FeishuSignal(code='300750', name='示例科技', signal='持有', price=180.50, reason='未触发买卖条件'),
    ]
    result = await FeishuNotificationService.send_signal_summary(signals, '2026-10-15')

    assert result is True
    assert '【模拟交易收盘信号】2026-10-15' in captured[0]
    for expected in ('600000 示例股份：买入', '000001 示例银行：卖出', '300750 示例科技：持有'):
        assert expected in captured[0]


@pytest.mark.asyncio
async def test_realtime_notifies_only_new_buy_and_sell_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    account = SimpleNamespace(
        id=1, account_name='default', strategy_name='ma', status='active', cash=1000000.0, initial_cash=1000000.0
    )
    universe = [
        SimpleNamespace(code='000001', name='新买入'),
        SimpleNamespace(code='000002', name='重复卖出'),
        SimpleNamespace(code='000003', name='新持有'),
    ]
    existing_signals = {
        '000001': None,
        '000002': SimpleNamespace(signal='卖出'),
        '000003': None,
    }
    sent: list[FeishuSignal] = []
    executed: list[str] = []
    db = FakeDb()

    async def fake_get_account(db_obj: Any, name: str) -> Any:
        return account if name == 'default' else None

    async def fake_get_universe(db_obj: Any, account_id: int) -> list[Any]:
        return universe

    async def fake_list_positions(db_obj: Any, account_id: int) -> list[Any]:
        return []

    async def fake_get_signal(db_obj: Any, account_id: int, code: str, signal_date: str) -> Any:
        return existing_signals[code]

    async def fake_update_signal(db_obj: Any, signal_id: int, **values: Any) -> None:
        return None

    async def fake_fetch_realtime(codes: list[str]) -> list[dict[str, Any]]:
        prices = {'000001': 10.0, '000002': 20.0, '000003': 30.0}
        return [{'code': code, 'price': prices[code]} for code in codes]

    def fake_compute_signal(strategy_name: str, code: str, params: Any, end_date: str, price: float) -> dict[str, Any]:
        directions = {'000001': '买入', '000002': '卖出', '000003': '持有'}
        return {'signal': directions[code], 'reason': f'{code}原因', 'close': price}

    async def fake_upsert_signal(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(id=len(executed) + 100)

    async def fake_execute_buy(*args: Any, **kwargs: Any) -> None:
        executed.append('买入')

    async def fake_execute_sell(*args: Any, **kwargs: Any) -> None:
        executed.append('卖出')

    async def fake_upsert_snapshot(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_send_signal_with_receipt(signal: FeishuSignal) -> FeishuSendResult:
        sent.append(signal)
        return FeishuSendResult(True, 'om_test')

    @asynccontextmanager
    async def fake_session(log_sql: bool = False) -> AsyncIterator[FakeDb]:
        yield db

    monkeypatch.setattr(DataSourceRegistry, 'session', fake_session)
    monkeypatch.setattr(StockPaperService, '_is_trading_day', staticmethod(lambda value: True))
    monkeypatch.setattr(StockPaperService, '_is_trading_time', staticmethod(lambda now=None: True))
    monkeypatch.setattr(StockPaperDao, 'get_account', fake_get_account)
    monkeypatch.setattr(StockPaperDao, 'get_universe', fake_get_universe)
    monkeypatch.setattr(StockPaperDao, 'list_positions', fake_list_positions)
    monkeypatch.setattr(StockPaperDao, 'get_signal', fake_get_signal)
    monkeypatch.setattr(StockPaperDao, 'update_signal', fake_update_signal)
    monkeypatch.setattr(StockRealtimeService, 'fetch_realtime', fake_fetch_realtime)
    monkeypatch.setattr(StockSignalService, 'compute_signal', staticmethod(fake_compute_signal))
    monkeypatch.setattr(StockPaperService, '_upsert_signal', fake_upsert_signal)
    monkeypatch.setattr(StockPaperService, '_execute_buy', fake_execute_buy)
    monkeypatch.setattr(StockPaperService, '_execute_sell', fake_execute_sell)
    monkeypatch.setattr(StockPaperService, '_upsert_snapshot', fake_upsert_snapshot)
    monkeypatch.setattr(
        FeishuNotificationService, 'send_signal_with_receipt', staticmethod(fake_send_signal_with_receipt)
    )

    result = await StockPaperService.run_realtime_signal_and_execute()
    await asyncio.sleep(0)

    assert result['executed'] == 2
    assert result['skipped'] == 0
    assert executed == ['买入']
    assert len(sent) == 1
    assert sent[0].code == '000001'
    assert sent[0].signal == '买入'
    assert db.committed >= 1


@pytest.mark.asyncio
async def test_eod_sends_summary_for_all_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    account = SimpleNamespace(id=1, account_name='default', strategy_name='ma', status='active')
    universe = [
        SimpleNamespace(code='600000', name='示例股份'),
        SimpleNamespace(code='000001', name='示例银行'),
        SimpleNamespace(code='300750', name='示例科技'),
    ]
    sent: list[list[FeishuSignal]] = []
    db = FakeDb()

    async def fake_get_account(db_obj: Any, name: str) -> Any:
        return account

    async def fake_get_universe(db_obj: Any, account_id: int) -> list[Any]:
        return universe

    async def fake_list_positions(db_obj: Any, account_id: int) -> list[Any]:
        return []

    def fake_fetch_close(code: str, end_date: str) -> float:
        prices = {'600000': 12.34, '000001': 8.90, '300750': 180.50}
        return prices[code]

    def fake_compute_signal(strategy_name: str, code: str, params: Any, end_date: str, price: float) -> dict[str, Any]:
        directions = {'600000': '买入', '000001': '卖出', '300750': '持有'}
        return {'signal': directions[code], 'reason': f'{code}原因', 'close': price}

    async def fake_upsert_signal(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(id=1)

    async def fake_upsert_snapshot(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_send_signal_summary_with_receipt(signals: list[FeishuSignal], signal_date: str) -> FeishuSendResult:
        sent.append(signals)
        assert signal_date
        return FeishuSendResult(True, 'om_summary')

    @asynccontextmanager
    async def fake_session(log_sql: bool = False) -> AsyncIterator[FakeDb]:
        yield db

    monkeypatch.setattr(DataSourceRegistry, 'session', fake_session)
    monkeypatch.setattr(StockPaperService, '_is_trading_day', staticmethod(lambda value: True))
    monkeypatch.setattr(StockPaperDao, 'get_account', fake_get_account)
    monkeypatch.setattr(StockPaperDao, 'get_universe', fake_get_universe)
    monkeypatch.setattr(StockPaperDao, 'list_positions', fake_list_positions)
    monkeypatch.setattr(StockPaperService, '_fetch_close', staticmethod(fake_fetch_close))
    monkeypatch.setattr(StockSignalService, 'compute_signal', staticmethod(fake_compute_signal))
    monkeypatch.setattr(StockPaperService, '_upsert_signal', fake_upsert_signal)
    monkeypatch.setattr(StockPaperService, '_upsert_snapshot', fake_upsert_snapshot)
    monkeypatch.setattr(
        FeishuNotificationService,
        'send_signal_summary_with_receipt',
        staticmethod(fake_send_signal_summary_with_receipt),
    )

    await StockPaperService.run_eod_signal()
    await asyncio.sleep(0)

    assert db.committed >= 1
    assert len(sent) == 1
    assert [signal.signal for signal in sent[0]] == ['买入', '卖出', '持有']


@pytest.mark.asyncio
async def test_send_text_app_returns_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_enabled', True)
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_mode', 'app')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_app_id', 'cli_test')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_app_secret', 'secret_test')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_chat_id', 'oc_test')
    monkeypatch.setattr(FeishuNotificationService, '_app_token', None)
    monkeypatch.setattr(FeishuNotificationService, '_app_token_expire_at', 0.0)
    requests: list[dict[str, Any]] = []

    class AppFakeAsyncClient:
        def __init__(self, timeout: Any = None) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> 'AppFakeAsyncClient':
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(
            self, url: str, json: dict[str, Any] | None = None, params: Any = None, headers: Any = None
        ) -> FakeResponse:
            requests.append({'url': str(url), 'json': json})
            if 'tenant_access_token' in url:
                return FakeResponse({'code': 0, 'tenant_access_token': 'token_test', 'expire': 7200})
            return FakeResponse({'code': 0, 'data': {'message_id': 'om_test'}})

    monkeypatch.setattr(httpx, 'AsyncClient', AppFakeAsyncClient)
    result = await FeishuNotificationService.send_text_with_receipt('测试消息')

    assert result.ok is True
    assert result.message_id == 'om_test'
    assert len(requests) == 2
    assert requests[1]['json']['content'] == '{"text":"测试消息"}'


@pytest.mark.asyncio
async def test_recall_message_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_enabled', True)
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_mode', 'app')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_app_id', 'cli_test')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_app_secret', 'secret_test')
    monkeypatch.setattr(FeishuNotificationService, '_app_token', 'token_test')
    monkeypatch.setattr(FeishuNotificationService, '_app_token_expire_at', float(time.monotonic() + 3600))
    requests: list[str] = []

    class RecallFakeAsyncClient:
        def __init__(self, timeout: Any = None) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> 'RecallFakeAsyncClient':
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def delete(self, url: str, headers: Any = None) -> FakeResponse:
            requests.append(str(url))
            return FakeResponse({'code': 0})

    monkeypatch.setattr(httpx, 'AsyncClient', RecallFakeAsyncClient)
    result = await FeishuNotificationService.recall_message('om_test')

    assert result.ok is True
    assert result.message_id == 'om_test'
    assert requests == ['https://open.feishu.cn/open-apis/im/v1/messages/om_test']

@pytest.mark.asyncio
async def test_recall_signal_notification_updates_status(monkeypatch: pytest.MonkeyPatch) -> None:
    message = SimpleNamespace(id=1, message_id='om_test', recall_status='sent')
    updated: list[dict[str, Any]] = []

    async def fake_get_feishu_message_by_signal(db: Any, signal_id: int, message_type: str) -> Any:
        assert signal_id == 1
        assert message_type == 'signal'
        return message

    async def fake_update_feishu_message(db: Any, message_id: int, **values: Any) -> None:
        updated.append(values)

    async def fake_recall_message(message_id: str) -> Any:
        return FeishuRecallResult(True, message_id)

    monkeypatch.setattr(StockPaperDao, 'get_feishu_message_by_signal', staticmethod(fake_get_feishu_message_by_signal))
    monkeypatch.setattr(StockPaperDao, 'update_feishu_message', staticmethod(fake_update_feishu_message))
    monkeypatch.setattr(FeishuNotificationService, 'recall_message', staticmethod(fake_recall_message))
    db = FakeDb()
    result = await StockPaperService.recall_signal_notification(db, 1, '信号作废')

    assert result == {'message_id': 'om_test', 'status': 'recalled'}
    assert updated[0]['recall_status'] == 'recalled'
    assert updated[0]['recall_reason'] == '信号作废'
    assert db.committed == 1
