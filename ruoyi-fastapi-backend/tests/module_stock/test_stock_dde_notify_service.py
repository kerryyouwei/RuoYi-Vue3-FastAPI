"""股票池 DDE 通知格式与东方财富数据清洗单元测试。"""

import json
from typing import Any

import httpx
import pytest

from config.env import FeishuNotifyConfig
from module_stock.service.stock_dde_notify_service import DDEStockRow, StockDDENotifyService
from module_stock.service.stock_feishu_notification_service import FeishuNotificationService


def _row(
    code: str,
    name: str,
    pct_change: float,
    large_net: float,
    market_cap: float,
    *,
    limit_up: bool = False,
) -> DDEStockRow:
    strength = large_net / market_cap * 100
    return DDEStockRow(
        code=code,
        name=name,
        price=3.45,
        pct_change=pct_change,
        large_net=large_net,
        market_cap=market_cap,
        strength=strength,
        limit_up=limit_up,
    )


def test_build_card_uses_required_title_and_core_fields() -> None:
    inflow = [
        _row('002437', '誉衡药业', 5.18, 1.083e9, 7.75e9),
        _row('000993', '闽东电力', 4.07, 5.50e8, 6.40e9),
    ]
    outflow = [
        _row('002343', '慈文传媒', 2.24, -2.58e8, 2.80e9),
        _row('002696', '百洋股份', -9.97, -1.76e8, 2.40e9),
    ]
    card = StockDDENotifyService._build_card(
        title='尾盘｜DDE 大单资金｜20261016',
        candidate_count=131,
        inflow_count=16,
        outflow_count=30,
        inflow_rows=inflow,
        outflow_rows=outflow,
        period='尾盘',
    )
    content = card['elements'][0]['text']['content']

    assert card['header']['title']['content'] == '尾盘｜DDE 大单资金｜20261016'
    assert '盘面速览　候选 131 只｜流入 16 只｜流出 30 只' in content
    assert "涨跌幅 <font color='red'>+5.18%</font>" in content
    assert "大单净额 <font color='red'>+10.83亿</font>" in content
    assert "强度 <font color='red'>+13.97%</font>" in content
    assert "涨跌幅 <font color='green'>-9.97%</font>" in content
    assert "大单净额 <font color='green'>-2.58亿</font>" in content
    assert "强度 <font color='green'>-9.21%</font>" in content
    assert '#1 誉衡药业（002437）' in content
    assert '#1 慈文传媒（002343）' in content
    assert '行业' not in content
    assert '走势概念' not in content
    assert '机构' not in content
    assert '联动' not in content


def test_normalize_row_parses_eastmoney_fields_and_strength() -> None:
    raw = {
        'f12': '002437.SZ',
        'f14': '誉衡药业',
        'f2': '3.45',
        'f3': 5.18,
        'f20': '7,750,000,000.00',
        'f21': '6,400,000,000.00',
        'f72': '1.083E9',
    }
    rows = StockDDENotifyService._normalize_rows([raw], [('002437', '誉衡药业')])

    assert len(rows) == 1
    row = rows[0]
    assert row.code == '002437'
    assert row.name == '誉衡药业'
    assert row.price == 3.45
    assert row.pct_change == 5.18
    assert row.large_net == 1.083e9
    assert row.market_cap == 7750000000.0
    assert row.limit_up is False
    assert row.strength == 13.974193548387096


def test_to_secid_by_market() -> None:
    assert StockDDENotifyService._to_secid('001246') == '0.001246'
    assert StockDDENotifyService._to_secid('600661') == '1.600661'


@pytest.mark.asyncio
async def test_fetch_market_rows_parses_eastmoney_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                'data': {
                    'diff': [
                        {
                            'f12': '001246.SZ',
                            'f14': '泓淋电力',
                            'f2': 31.2,
                            'f3': -0.5,
                            'f20': 45656989489.016,
                            'f21': 4910162400.0,
                            'f72': -446720.91,
                        }
                    ]
                }
            }

    class FakeAsyncClient:
        def __init__(self, timeout: Any = None, headers: Any = None) -> None:
            captured['timeout'] = timeout
            captured['headers'] = headers

        async def __aenter__(self) -> 'FakeAsyncClient':
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str, params: dict[str, str] | None = None) -> FakeResponse:
            captured['url'] = url
            captured['params'] = params
            return FakeResponse()

    monkeypatch.setattr(httpx, 'AsyncClient', FakeAsyncClient)
    rows = await StockDDENotifyService._fetch_market_rows(['001246', '600661'])

    assert len(rows) == 1
    assert rows[0]['f12'] == '001246.SZ'
    assert captured['params']['secids'] == '0.001246,1.600661'
    assert captured['params']['pz'] == '2'
    assert captured['params']['fields'] == 'f12,f14,f2,f3,f20,f21,f72'


def test_limit_up_detection_by_board_and_name() -> None:
    assert StockDDENotifyService._is_limit_up('002437', '誉衡药业', 9.9)
    assert StockDDENotifyService._is_limit_up('300001', '创业板', 19.9)
    assert StockDDENotifyService._is_limit_up('600001', 'ST示例', 4.9)
    assert not StockDDENotifyService._is_limit_up('002437', '誉衡药业', 5.18)


@pytest.mark.asyncio
async def test_send_card_with_receipt_sends_interactive_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_enabled', True)
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_notify_mode', 'app')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_app_id', 'app')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_app_secret', 'secret')
    monkeypatch.setattr(FeishuNotifyConfig, 'feishu_chat_id', 'chat')
    monkeypatch.setattr(FeishuNotificationService, '_get_app_token', staticmethod(_fake_token))

    requests: list[dict[str, Any]] = []

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {'code': 0, 'data': {'message_id': 'om_test'}}

    class FakeAsyncClient:
        def __init__(self, timeout: Any = None) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> 'FakeAsyncClient':
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(
            self,
            url: str,
            json: dict[str, Any],
            params: dict[str, str] | None = None,
            headers: dict[str, str] | None = None,
        ) -> FakeResponse:
            requests.append(json)
            return FakeResponse()

    monkeypatch.setattr(httpx, 'AsyncClient', FakeAsyncClient)

    result = await FeishuNotificationService.send_card_with_receipt({'header': {'title': {'content': 'test'}}})

    assert result.ok is True
    assert result.message_id == 'om_test'
    assert requests[0]['msg_type'] == 'interactive'
    assert json.loads(requests[0]['content']) == {'header': {'title': {'content': 'test'}}}


async def _fake_token(client: httpx.AsyncClient) -> str:
    return 'token'
