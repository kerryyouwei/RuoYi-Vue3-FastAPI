"""函数层积木：出场（exit）纯函数。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ExitFunc:
    name: str
    version: str
    params: dict[str, object]
    fn: Callable[..., bool]

    def __call__(self, **kwargs: object) -> bool:
        params = {**self.params, **kwargs}
        return self.fn(**params)


def fixed_days_exit(entry_bar: int, current_bar: int, days: int = 10) -> bool:
    """持有满 N 个交易日出场。"""
    return current_bar - entry_bar >= days


def atr_trailing_exit(
    window: pd.DataFrame,
    highest_close: float,
    entry_price: float,
    period: int = 14,
    mult: float = 3.0,
) -> bool:
    """ATR 吊灯止损：收盘 < 持有期最高收盘 - mult*ATR。"""
    if len(window) < period + 1:
        return False
    recent = window.iloc[-(period + 1) :]
    prev_close = recent['close'].shift(1)
    tr = pd.concat(
        [
            recent['high'] - recent['low'],
            (recent['high'] - prev_close).abs(),
            (recent['low'] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(tr.iloc[1:].mean())
    if atr <= 0:
        return False
    stop = highest_close - mult * atr
    close = float(window['close'].iloc[-1])
    return bool(close < stop and close < entry_price)


EXITS: dict[str, ExitFunc] = {
    'fixed_days': ExitFunc('fixed_days', '1.0.0', {'days': 10}, fixed_days_exit),
    'atr_trailing': ExitFunc('atr_trailing', '1.0.0', {'period': 14, 'mult': 3.0}, atr_trailing_exit),
}
