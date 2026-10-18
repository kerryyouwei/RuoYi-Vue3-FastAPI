"""函数层积木：买点（entry）纯函数与注册表。

约定：
- 输入 window 为截至当前 K 线（含）的 DataFrame，索引为日期，
  至少包含 open/high/low/close/volume 列；
- 输出 True = 明日开盘买入信号，False = 无信号；
- 每个函数必须通过 golden_tests 的未来数据探针。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class FuncMeta:
    name: str
    version: str
    params: dict[str, object]
    min_bars: int
    description: str = ''
    golden_cases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EntryFunc:
    meta: FuncMeta
    fn: Callable[..., bool]

    def __call__(self, window: pd.DataFrame, **overrides: object) -> bool:
        params = {**self.meta.params, **overrides}
        return self.fn(window, **params)


def breakout_20d(window: pd.DataFrame, lookback: int = 20) -> bool:
    """收盘价突破前 lookback 日最高收盘价 → 买入信号。"""
    if len(window) < lookback + 1:
        return False
    close = window['close']
    prior_max = close.iloc[-lookback - 1 : -1].max()
    return bool(close.iloc[-1] > prior_max)


def mom_breakout(window: pd.DataFrame, period: int = 20, threshold: float = 0.05) -> bool:
    """period 日动量超过阈值 → 买入信号。"""
    if len(window) < period + 1:
        return False
    close = window['close']
    base = close.iloc[-period - 1]
    if base <= 0:
        return False
    return bool(close.iloc[-1] / base - 1 > threshold)


ENTRIES: dict[str, EntryFunc] = {
    'breakout_20d': EntryFunc(
        meta=FuncMeta(
            name='breakout_20d',
            version='1.0.0',
            params={'lookback': 20},
            min_bars=21,
            description='收盘价突破前N日最高收盘价',
            golden_cases=('常规趋势样本', '数据不足样本', '未来数据探针'),
        ),
        fn=breakout_20d,
    ),
    'mom_breakout': EntryFunc(
        meta=FuncMeta(
            name='mom_breakout',
            version='1.0.0',
            params={'period': 20, 'threshold': 0.05},
            min_bars=21,
            description='N日动量超过阈值',
            golden_cases=('常规趋势样本', '数据不足样本', '未来数据探针'),
        ),
        fn=mom_breakout,
    ),
}
