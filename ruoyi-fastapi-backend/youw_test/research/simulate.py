"""裸信号模拟器：固定仓位 + 固定出场，第一/二轮广筛共用。

执行规则（《股票池回测思路.md》2.1/6.1）：
- 信号 t 收盘生成；t+1 开盘成交；
- t+1 开盘涨停 → 放弃该信号（不做顺延，广筛阶段保守处理）；
- 出场日开盘跌停 → 顺延至下一个可成交开盘；
- 成本：佣金万2.5×2 + 印花税千0.5 + 滑点 0.1%×2（可覆盖）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .funcs.entry import ENTRIES, EntryFunc
from .funcs.filter import FILTERS, FilterFunc
from .funcs.exit import EXITS, ExitFunc
from .funcs.market_rules import limit_prices, is_tradable_row

BASE_COST = 0.00025 * 2 + 0.0005 + 0.001 * 2  # 佣金往返 + 印花税 + 滑点往返


@dataclass
class Trade:
    code: str
    signal_date: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    ret: float
    hold_days: int

    def as_dict(self) -> dict[str, Any]:
        return {
            'code': self.code,
            'signalDate': self.signal_date,
            'entryDate': self.entry_date,
            'exitDate': self.exit_date,
            'entryPrice': round(self.entry_price, 4),
            'exitPrice': round(self.exit_price, 4),
            'ret': round(self.ret, 6),
            'holdDays': self.hold_days,
        }


@dataclass
class ScanContext:
    frames: dict[str, pd.DataFrame]
    entry: EntryFunc
    filters: list[FilterFunc] = field(default_factory=list)
    exit_fn: ExitFunc = field(default_factory=lambda: EXITS['fixed_days'])
    max_positions: int = 5
    cost: float = BASE_COST


def _limit_up_tomorrow(frame: pd.DataFrame, i: int, is_st: bool) -> float | None:
    """t+1 涨停价 = close(t) × (1+ratio)。"""
    if i < 0 or i >= len(frame):
        return None
    code = str(frame.attrs.get('code', ''))
    ratio_board = 0.20 if code.startswith(('300', '301', '688', '689')) else 0.10
    ratio = 0.05 if is_st else ratio_board
    return round(float(frame['close'].iloc[i]) * (1 + ratio), 2)


def run_scan(ctx: ScanContext, start: str | None = None, end: str | None = None) -> list[Trade]:
    """对整个股票池执行裸信号模拟，返回逐笔交易。"""
    trades: list[Trade] = []
    min_bars = ctx.entry.meta.min_bars
    for code, frame in ctx.frames.items():
        frame = frame.sort_index()
        if start is not None:
            frame = frame[frame.index >= pd.Timestamp(start)]
        if end is not None:
            frame = frame[frame.index <= pd.Timestamp(end)]
        if frame.empty or len(frame) < min_bars + 2:
            continue
        trades.extend(_scan_one(code, frame, ctx, min_bars))
    return trades


def _scan_one(code: str, frame: pd.DataFrame, ctx: ScanContext, min_bars: int) -> list[Trade]:
    trades: list[Trade] = []
    dates = frame.index
    # 开仓中的交易：code 级别同时最多一笔（单标的串行）
    open_trade: dict[str, Any] | None = None
    positions = 0  # 池级并发控制由调用方在外层维护；单标的内最多 1 笔

    for i in range(min_bars, len(frame) - 1):
        row = frame.iloc[i]
        if open_trade is not None:
            # 检查出场：fixed_days → entry_i + days 的开盘；跌停顺延
            exit_fn = ctx.exit_fn
            should_exit = False
            if exit_fn.name == 'fixed_days':
                should_exit = exit_fn(entry_bar=open_trade['entry_i'], current_bar=i)
            else:  # atr_trailing 等基于窗口的出场
                window = frame.iloc[max(0, open_trade['entry_i'] - 30) : i + 1]
                should_exit = exit_fn(
                    window=window,
                    highest_close=max(
                        frame['close'].iloc[open_trade['entry_i'] : i + 1].max(),
                        open_trade['entry_price'],
                    ),
                    entry_price=open_trade['entry_price'],
                )
            if should_exit:
                filled = _try_exit(frame, i, open_trade, ctx.cost)
                if filled is not None:
                    trades.append(filled)
                    open_trade = None
                    positions -= 1
            continue

        # 无持仓：评估买点
        window = frame.iloc[: i + 1]
        if not ctx.entry(window):
            continue
        row_dict = row.to_dict() if hasattr(row, 'to_dict') else dict(row)
        if not all(f(row_dict) for f in ctx.filters):
            continue
        if not is_tradable_row(row_dict):
            continue
        if positions >= ctx.max_positions:
            continue
        next_row = frame.iloc[i + 1]
        next_dict = next_row.to_dict() if hasattr(next_row, 'to_dict') else dict(next_row)
        if not is_tradable_row(next_dict):
            continue
        is_st = bool(row_dict.get('isst') or 0) or bool(next_dict.get('isst') or 0)
        limit_up = _limit_up_tomorrow(frame, i, is_st)
        entry_open = float(next_row['open'])
        if limit_up is not None and entry_open >= limit_up:
            continue  # 开盘涨停，放弃信号
        open_trade = {
            'signal_date': str(dates[i].date()),
            'entry_i': i + 1,
            'entry_date': str(dates[i + 1].date()),
            'entry_price': entry_open,
        }
        positions += 1

    # 区间结束仍有持仓：按最后一根开盘强平（计入统计）
    if open_trade is not None:
        last_i = len(frame) - 1
        exit_open = float(frame['open'].iloc[last_i])
        trades.append(
            Trade(
                code=code,
                signal_date=open_trade['signal_date'],
                entry_date=open_trade['entry_date'],
                exit_date=str(dates[last_i].date()),
                entry_price=open_trade['entry_price'],
                exit_price=exit_open,
                ret=exit_open / open_trade['entry_price'] - 1 - ctx.cost,
                hold_days=last_i - open_trade['entry_i'],
            )
        )
    return trades


def _try_exit(frame: pd.DataFrame, i: int, open_trade: dict[str, Any], cost: float = BASE_COST) -> Trade | None:
    """尝试在 i+1 开盘卖出；开盘跌停则顺延（返回 None）。"""
    if i + 1 >= len(frame):
        return None
    next_row = frame.iloc[i + 1]
    next_dict = next_row.to_dict() if hasattr(next_row, 'to_dict') else dict(next_row)
    if not is_tradable_row(next_dict):
        return None
    code = str(frame.attrs.get('code', ''))
    is_st = bool(next_dict.get('isst') or 0)
    ratio = 0.05 if is_st else (0.20 if code.startswith(('300', '301', '688', '689')) else 0.10)
    limit_down = round(float(frame['close'].iloc[i]) * (1 - ratio), 2)
    exit_open = float(next_row['open'])
    if exit_open <= limit_down:
        return None  # 开盘跌停，顺延
    ret = exit_open / open_trade['entry_price'] - 1 - cost
    return Trade(
        code=code,
        signal_date=open_trade['signal_date'],
        entry_date=open_trade['entry_date'],
        exit_date=str(frame.index[i + 1].date()),
        entry_price=open_trade['entry_price'],
        exit_price=exit_open,
        ret=ret,
        hold_days=i + 1 - open_trade['entry_i'],
    )


def summarize(trades: list[Trade]) -> dict[str, Any]:
    """统计样本量 / 胜率 / 跨年一致性 / 跨股票覆盖。"""
    if not trades:
        return {'nTrades': 0}
    import pandas as pd

    frame = pd.DataFrame([t.as_dict() for t in trades])
    frame['year'] = frame['entryDate'].str[:4]
    yearly = frame.groupby('year')['ret'].agg(['count', 'mean', lambda s: (s > 0).mean()])
    yearly.columns = ['count', 'meanRet', 'winRate']
    by_stock = frame.groupby('code')['ret'].agg(['count', lambda s: (s > 0).mean()])
    by_stock.columns = ['count', 'winRate']
    profitable_stocks = float((by_stock['winRate'] > 0.5).mean()) if len(by_stock) else 0.0
    return {
        'nTrades': int(len(frame)),
        'winRate': round(float((frame['ret'] > 0).mean()), 4),
        'avgRet': round(float(frame['ret'].mean()), 6),
        'totalRet': round(float((1 + frame['ret']).prod() - 1), 6),
        'yearly': {str(year): {'count': int(row['count']), 'winRate': round(float(row['winRate']), 4)} for year, row in yearly.iterrows()},
        'stockCoverage': {
            'nStocks': int(len(by_stock)),
            'profitableRatio': round(profitable_stocks, 4),
        },
    }

