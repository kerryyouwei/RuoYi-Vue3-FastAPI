"""交易信号计算服务单元测试。"""

from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from exceptions.exception import ServiceException
from module_stock.service.stock_signal_service import StockSignalService
from module_stock.service.stock_strategy_service import StockStrategyService


def _make_daily_data(closes: list[float], start: str = '2024-01-01') -> pd.DataFrame:
    """构造合成日线 DataFrame，columns=open/high/low/close/volume。"""
    dates = pd.bdate_range(start=start, periods=len(closes))
    frame = pd.DataFrame(
        {
            'open': closes,
            'high': [c * 1.01 for c in closes],
            'low': [c * 0.99 for c in closes],
            'close': closes,
            'volume': [1_000_000] * len(closes),
        },
        index=dates,
    )
    return frame


def test_compute_signal_returns_hold_on_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        StockStrategyService, '_load_stock_data', staticmethod(lambda code, start, end: None)
    )
    monkeypatch.setattr(
        StockStrategyService, '_coerce_strategy_params', classmethod(lambda cls, name, params: {})
    )
    monkeypatch.setattr(
        StockStrategyService, '_strategy_warmup_bars', staticmethod(lambda cls, params: 10)
    )
    monkeypatch.setattr(
        StockStrategyService, '_warmup_start_date', staticmethod(lambda start, bars: start)
    )
    monkeypatch.setattr(
        StockStrategyService, '_load_strategy_cls', staticmethod(lambda name: MagicMock()), raising=False
    )

    with patch('youw_test.strategies.load_strategy', return_value=MagicMock()):
        result = StockSignalService.compute_signal('ma', '000001', {}, '2024-12-31')
    assert result['signal'] == '持有'
    assert result['close'] is None


def test_compute_signal_invalid_strategy_params(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_coerce(cls, strategy_name: str, values: dict[str, Any]) -> dict[str, Any]:
        raise ServiceException(message='未知策略参数')

    monkeypatch.setattr(
        StockStrategyService, '_coerce_strategy_params', classmethod(fake_coerce)
    )
    with pytest.raises(ServiceException):
        StockSignalService.compute_signal('ma', '000001', {'unknown': 1}, '2024-12-31')


def test_compute_signal_with_synthetic_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """合成数据验证：有历史数据时返回信号结果（不依赖真实策略文件，仅验证流程）。"""
    data = _make_daily_data([10.0, 10.5, 11.0, 10.8, 11.2] * 10)
    strategy_cls = MagicMock()
    monkeypatch.setattr(
        StockStrategyService, '_coerce_strategy_params', classmethod(lambda cls, name, params: {})
    )
    monkeypatch.setattr(
        StockStrategyService, '_strategy_warmup_bars', staticmethod(lambda cls, params: 10)
    )
    monkeypatch.setattr(
        StockStrategyService, '_warmup_start_date', staticmethod(lambda start, bars: start)
    )
    monkeypatch.setattr(
        StockStrategyService, '_load_stock_data', staticmethod(lambda code, start, end: data)
    )
    monkeypatch.setattr(
        StockStrategyService, '_live_start_strategy', staticmethod(lambda cls, date: strategy_cls)
    )

    fake_strategy = MagicMock()
    fake_strategy.signal = '买入'
    fake_strategy.signal_reason = 'test reason'

    def fake_run(self: Any) -> list[Any]:
        return [fake_strategy]

    with patch('backtrader.Cerebro') as MockCerebro:
        instance = MockCerebro.return_value
        instance.run.side_effect = fake_run
        result = StockSignalService.compute_signal('ma', '000001', {}, '2024-12-31')

    assert result['signal'] == '买入'
    assert result['reason'] == 'test reason'
    assert result['close'] == pytest.approx(data['close'].iloc[-1])


def test_compute_signal_hold_when_no_signal_set(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _make_daily_data([10.0, 10.5, 11.0])
    strategy_cls = MagicMock()
    monkeypatch.setattr(
        StockStrategyService, '_coerce_strategy_params', classmethod(lambda cls, name, params: {})
    )
    monkeypatch.setattr(
        StockStrategyService, '_strategy_warmup_bars', staticmethod(lambda cls, params: 10)
    )
    monkeypatch.setattr(
        StockStrategyService, '_warmup_start_date', staticmethod(lambda start, bars: start)
    )
    monkeypatch.setattr(
        StockStrategyService, '_load_stock_data', staticmethod(lambda code, start, end: data)
    )
    monkeypatch.setattr(
        StockStrategyService, '_live_start_strategy', staticmethod(lambda cls, date: strategy_cls)
    )

    fake_strategy = MagicMock()
    fake_strategy.signal = None
    fake_strategy.signal_reason = ''

    with patch('backtrader.Cerebro') as MockCerebro:
        instance = MockCerebro.return_value
        instance.run.return_value = [fake_strategy]
        result = StockSignalService.compute_signal('ma', '000001', {}, '2024-12-31')

    assert result['signal'] == '持有'
