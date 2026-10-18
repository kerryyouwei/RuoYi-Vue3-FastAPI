"""函数层积木：过滤器（filter）与出场（exit）纯函数。"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd


def _get(row: pd.Series | dict, key: str) -> float | None:
    value = row.get(key) if hasattr(row, 'get') else None
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(value):
        return None
    return value


@dataclass(frozen=True)
class FilterFunc:
    name: str
    version: str
    params: dict[str, object]
    fn: Callable[..., bool]

    def __call__(self, row: pd.Series | dict, **overrides: object) -> bool:
        params = {**self.params, **overrides}
        return self.fn(row, **params)


def turnover_filter(row: pd.Series | dict, min_turnover: float = 0.3, max_turnover: float = 20.0) -> bool:
    """换手率在 [min, max] 区间内才允许交易（%）。缺失字段不阻止。"""
    turn = _get(row, 'turn')
    if turn is None:
        return True
    return min_turnover <= turn <= max_turnover


def st_filter(row: pd.Series | dict) -> bool:
    """非 ST 才允许交易；缺失字段不阻止。"""
    isst = _get(row, 'isst')
    return isst is None or isst < 0.5


def liquidity_filter(row: pd.Series | dict, min_amount: float = 5_000_000) -> bool:
    """成交额达到门槛才允许交易（元）；缺失字段不阻止。"""
    amount = _get(row, 'amount')
    return amount is None or amount >= min_amount


FILTERS: dict[str, FilterFunc] = {
    'turnover': FilterFunc('turnover', '1.0.0', {'min_turnover': 0.3, 'max_turnover': 20.0}, turnover_filter),
    'st': FilterFunc('st', '1.0.0', {}, st_filter),
    'liquidity': FilterFunc('liquidity', '1.0.0', {'min_amount': 5_000_000}, liquidity_filter),
}

