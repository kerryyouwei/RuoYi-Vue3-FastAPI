"""A股市场规则纯函数：涨跌停价格、可交易性标记、T+1 台账辅助。

所有函数只依赖传入的数据行，不访问任何全局状态，保证可独立做黄金测试。
增强字段缺失（NaN / 不存在）时一律降级为"不阻止"，由调用方决定兜底语义。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

MIN_LISTED_DAYS = 120

STANDARD_LIMIT = 0.10  # 主板
GEM_STAR_LIMIT = 0.20  # 创业板 300/301、科创板 688/689
ST_LIMIT = 0.05  # ST 股

_GEM_STAR_PREFIXES = ('300', '301', '688', '689')


def _get(row: Mapping[str, Any] | Any, key: str) -> float | None:
    """取行字段，缺失或 NaN 返回 None。"""
    try:
        value = row[key] if hasattr(row, '__getitem__') else getattr(row, key, None)
    except (KeyError, IndexError, TypeError):
        return None
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(value):
        return None
    return value


def limit_ratio(code: str, is_st: bool = False) -> float:
    """按板块与 ST 状态返回涨跌停幅度。北交所暂不支持（按主板处理）。"""
    code = str(code)
    if code.startswith(_GEM_STAR_PREFIXES):
        return GEM_STAR_LIMIT
    if is_st:
        return ST_LIMIT
    return STANDARD_LIMIT


def limit_prices(preclose: float, code: str, is_st: bool = False) -> tuple[float, float]:
    """返回 (涨停价, 跌停价)，按 A 股惯例保留两位小数。"""
    ratio = limit_ratio(code, is_st)
    return round(preclose * (1 + ratio), 2), round(preclose * (1 - ratio), 2)


def buy_limit_price(preclose: float, code: str, is_st: bool = False) -> float:
    """买入限价 = 涨停价 - 0.01。

    t+1 开盘封涨停（open == 涨停价）时限价单无法成交；正常开盘价低于
    该限价时按开盘价成交，实现"开盘价成交、封板不成交"的执行约束。
    """
    up, _ = limit_prices(preclose, code, is_st)
    return round(up - 0.01, 2)


def sell_limit_price(preclose: float, code: str, is_st: bool = False) -> float:
    """卖出限价 = 跌停价 + 0.01（开盘封跌停则无法成交）。"""
    _, down = limit_prices(preclose, code, is_st)
    return round(down + 0.01, 2)


def is_tradable_row(
    row: Mapping[str, Any] | Any,
    listed_days: float | None = None,
    min_amount: float | None = None,
    min_turn: float | None = None,
) -> bool:
    """判断某股票某日是否可交易。

    tradable = 非停牌 and 非ST and 上市>N天 and (可选)成交额/换手率达标。
    增强字段缺失时逐项降级；volume 缺失不阻止（普通 OHLCV 数据源）。
    """
    volume = _get(row, 'volume')
    if volume is not None and volume <= 0:
        return False
    tradestatus = _get(row, 'tradestatus')
    if tradestatus is not None and tradestatus < 0.5:
        return False  # 停牌
    isst = _get(row, 'isst')
    if isst is not None and isst > 0.5:
        return False  # ST
    if listed_days is not None and listed_days < MIN_LISTED_DAYS:
        return False  # 上市不足
    if min_amount is not None:
        amount = _get(row, 'amount')
        if amount is not None and amount < min_amount:
            return False
    if min_turn is not None:
        turn = _get(row, 'turn')
        if turn is not None and turn < min_turn:
            return False
    return True


def is_st_row(row: Mapping[str, Any] | Any) -> bool:
    """行内 isST 字段是否标记为 ST；缺失返回 False。"""
    isst = _get(row, 'isst')
    return isst is not None and isst > 0.5


class T1Ledger:
    """T+1 台账：记录每次买入成交的 bar 序号，禁止买入当日卖出。"""

    def __init__(self) -> None:
        self._filled_bar: dict[str, int] = {}

    def record_buy_fill(self, code: str, bar_no: int) -> None:
        self._filled_bar[code] = bar_no

    def can_sell(self, code: str, bar_no: int) -> bool:
        """买入成交当日（同 bar）禁止卖出。"""
        filled = self._filled_bar.get(code)
        return filled is None or filled != bar_no

    def clear(self, code: str) -> None:
        self._filled_bar.pop(code, None)
