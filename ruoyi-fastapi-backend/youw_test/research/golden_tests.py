"""黄金测试集：常规样本 / 边界样本 / 未来数据探针。

运行：python -m youw_test.research.golden_tests
全部通过返回退出码 0；任何失败打印明细并返回 1。
"""

from __future__ import annotations

import copy
import sys

import numpy as np
import pandas as pd

from .funcs.entry import ENTRIES, EntryFunc


def make_frame(closes: list[float], start: str = '2024-01-01') -> pd.DataFrame:
    """用收盘价构造合成日线（open=close 平移 1%，high/low 包络，volume 固定）。"""
    index = pd.date_range(start, periods=len(closes), freq='B')
    closes_arr = np.asarray(closes, dtype=float)
    opens = closes_arr * 0.99
    highs = np.maximum(opens, closes_arr) * 1.01
    lows = np.minimum(opens, closes_arr) * 0.99
    return pd.DataFrame(
        {
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes_arr,
            'volume': np.full(len(closes_arr), 10000.0),
        },
        index=index,
    )


def probe_future_data(entry: EntryFunc, closes: list[float]) -> bool:
    """未来数据探针：篡改信号日之后的 K 线，信号输出必须不变。"""
    frame = make_frame(closes)
    n = len(frame)
    signal_at = n - 3  # 在末尾第 3 根 K 线处取信号
    original = bool(entry(frame.iloc[: signal_at + 1]))
    tampered = copy.deepcopy(frame)
    tampered.iloc[signal_at + 1 :, :] = tampered.iloc[signal_at + 1 :, :].values * 3.0
    after = bool(entry(tampered.iloc[: signal_at + 1]))
    return original == after


def run_all() -> list[tuple[str, bool, str]]:
    """执行全部黄金测试，返回 (用例名, 是否通过, 说明)。"""
    results: list[tuple[str, bool, str]] = []

    # ---- 常规样本：稳定上涨序列应触发突破 ----
    uptrend = list(np.linspace(10, 20, 40))
    for name, entry in ENTRIES.items():
        hit = bool(entry(make_frame(uptrend)))
        results.append((f'{name}: 常规上升趋势触发信号', hit, f'输出={hit}'))

    # ---- 常规样本：单边下跌不应触发 ----
    downtrend = list(np.linspace(20, 10, 40))
    for name, entry in ENTRIES.items():
        hit = bool(entry(make_frame(downtrend)))
        results.append((f'{name}: 常规下跌不触发信号', not hit, f'输出={hit}'))

    # ---- 边界样本：数据不足必须返回 False（不抛异常） ----
    short = list(np.linspace(10, 12, 5))
    for name, entry in ENTRIES.items():
        try:
            hit = bool(entry(make_frame(short)))
            ok = hit is False
            detail = f'输出={hit}'
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f'异常 {type(exc).__name__}: {exc}'
        results.append((f'{name}: 数据不足返回False', ok, detail))

    # ---- 边界样本：除权日跳空（价格腰斩）不抛异常 ----
    ex_div = list(np.linspace(10, 15, 30)) + [7.5] * 10
    for name, entry in ENTRIES.items():
        try:
            bool(entry(make_frame(ex_div)))
            ok, detail = True, '无异常'
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f'异常 {type(exc).__name__}: {exc}'
        results.append((f'{name}: 除权跳空样本', ok, detail))

    # ---- 未来数据探针 ----
    probe_series = list(np.linspace(10, 15, 30)) + list(np.linspace(15, 14, 5))
    for name, entry in ENTRIES.items():
        ok = probe_future_data(entry, probe_series)
        results.append((f'{name}: 未来数据探针', ok, '篡改未来K线输出不变' if ok else '输出受未来数据影响'))

    return results


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    results = run_all()
    failures = [r for r in results if not r[1]]
    for name, ok, detail in results:
        mark = '✅' if ok else '❌'
        print(f'{mark} {name}  ({detail})')
    print(f'\n共 {len(results)} 项，通过 {len(results) - len(failures)} 项，失败 {len(failures)} 项')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())

