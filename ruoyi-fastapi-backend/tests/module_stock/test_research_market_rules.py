"""市场规则纯函数测试：涨跌停定价 / 可交易性 / T+1 台账。"""

import math

import pandas as pd
import pytest

from youw_test.research.funcs.market_rules import (
    T1Ledger,
    buy_limit_price,
    is_st_row,
    is_tradable_row,
    limit_prices,
    limit_ratio,
    sell_limit_price,
)


# ---------------------------------------------------------------- 涨跌停定价


def test_limit_ratio_by_board() -> None:
    assert limit_ratio('600519') == pytest.approx(0.10)
    assert limit_ratio('000001') == pytest.approx(0.10)
    assert limit_ratio('300750') == pytest.approx(0.20)
    assert limit_ratio('301236') == pytest.approx(0.20)
    assert limit_ratio('688981') == pytest.approx(0.20)
    assert limit_ratio('000001', is_st=True) == pytest.approx(0.05)


def test_limit_prices_rounding() -> None:
    up, down = limit_prices(10.00, '600519')
    assert up == pytest.approx(11.00)
    assert down == pytest.approx(9.00)

    up, down = limit_prices(10.37, '300750')
    assert up == pytest.approx(12.44)
    assert down == pytest.approx(8.30)


def test_buy_limit_price_blocks_limit_up_open() -> None:
    """买入限价 = 涨停价-0.01：开盘封涨停时不成交。"""
    preclose = 10.00
    limit_up, _ = limit_prices(preclose, '600519')
    buy_price = buy_limit_price(preclose, '600519')

    assert buy_price == pytest.approx(limit_up - 0.01)
    # 开盘涨停价 > 买入限价 → 限价单不成交
    assert limit_up > buy_price
    # 正常开盘价（涨停以下）≤ 限价 → 可成交
    assert preclose * 1.05 <= buy_price


def test_sell_limit_price_blocks_limit_down_open() -> None:
    preclose = 10.00
    _, limit_down = limit_prices(preclose, '600519')
    sell_price = sell_limit_price(preclose, '600519')

    assert sell_price == pytest.approx(limit_down + 0.01)
    assert limit_down < sell_price
    assert preclose * 0.95 >= sell_price


# ---------------------------------------------------------------- 可交易性


def test_tradable_requires_positive_volume() -> None:
    assert is_tradable_row({'volume': 0}) is False
    assert is_tradable_row({'volume': 100}) is True
    assert is_tradable_row({}) is True  # 缺失 volume 降级不阻止


def test_tradable_suspend_flag() -> None:
    assert is_tradable_row({'volume': 100, 'tradestatus': 0}) is False
    assert is_tradable_row({'volume': 100, 'tradestatus': 1}) is True


def test_tradable_st_flag() -> None:
    assert is_tradable_row({'volume': 100, 'isst': 1}) is False
    assert is_tradable_row({'volume': 100, 'isst': 0}) is True


def test_tradable_listed_days() -> None:
    assert is_tradable_row({'volume': 100}, listed_days=30) is False
    assert is_tradable_row({'volume': 100}, listed_days=119) is False
    assert is_tradable_row({'volume': 100}, listed_days=120) is True
    assert is_tradable_row({'volume': 100}, listed_days=None) is True  # 降级


def test_tradable_amount_and_turnover_threshold() -> None:
    assert is_tradable_row({'volume': 100, 'amount': 1_000_000}, min_amount=5_000_000) is False
    assert is_tradable_row({'volume': 100, 'amount': 6_000_000}, min_amount=5_000_000) is True
    assert is_tradable_row({'volume': 100, 'turn': 0.1}, min_turn=0.3) is False
    assert is_tradable_row({'volume': 100, 'turn': 1.0}, min_turn=0.3) is True


def test_tradable_nan_values_degrade() -> None:
    row = {'volume': 100, 'tradestatus': math.nan, 'isst': math.nan, 'amount': math.nan, 'turn': math.nan}
    assert is_tradable_row(row) is True


def test_is_st_row() -> None:
    assert is_st_row({'isst': 1}) is True
    assert is_st_row({'isst': 0}) is False
    assert is_st_row({'isst': math.nan}) is False
    assert is_st_row({}) is False


# ---------------------------------------------------------------- T+1 台账


def test_t1_ledger_blocks_same_bar_sell() -> None:
    ledger = T1Ledger()
    assert ledger.can_sell('A', 10) is True
    ledger.record_buy_fill('A', 10)
    assert ledger.can_sell('A', 10) is False
    assert ledger.can_sell('A', 11) is True


def test_t1_ledger_multiple_codes() -> None:
    ledger = T1Ledger()
    ledger.record_buy_fill('A', 5)
    ledger.record_buy_fill('B', 7)
    assert ledger.can_sell('A', 7) is True
    assert ledger.can_sell('B', 7) is False


# ---------------------------------------------------------------- 降级路径：模拟策略端 line 读取


def test_strategy_line_degradation_with_nan() -> None:
    """增强字段 NaN 时，is_tradable_row 逐项降级不阻止交易。"""
    frame = pd.DataFrame(
        {
            'volume': [100.0, 100.0],
            'amount': [math.nan, math.nan],
            'tradestatus': [math.nan, math.nan],
            'isst': [math.nan, math.nan],
            'turn': [math.nan, math.nan],
        }
    )
    for _, row in frame.iterrows():
        assert is_tradable_row(row, listed_days=200) is True
