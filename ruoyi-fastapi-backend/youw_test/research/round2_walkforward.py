"""第二轮：买点+过滤+出场组合 walk-forward 验证。

用法（在 ruoyi-fastapi-backend 目录下）：
  python -m youw_test.research.round2_walkforward --codes 000001,600519 \
      --start 2019-01-01 --end 2025-12-31

每个窗口：训练段选参数（小网格）→ 冻结 → 验证段运行 → 只记验证段。
拼接所有验证段形成样本外曲线，产出 results/round2.json。
组合数控制在 entries × filter sets × exits ≤ 10×5×5，按经济含义优先。
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

from .funcs.entry import ENTRIES, EntryFunc
from .funcs.exit import EXITS
from .funcs.filter import FILTERS, FilterFunc
from .funcs.risk import walk_forward_windows
from .funcs.stats import benjamini_hochberg, binom_two_sided_pvalue
from .simulate import ScanContext, Trade, run_scan, summarize

RESULTS_DIR = Path(__file__).resolve().parent / 'results'
MIN_TRAIN_TRADES = 20

# 小参数网格：每个 entry 向上下各偏 1 档
ENTRY_GRID: dict[str, list[dict]] = {
    'breakout_20d': [{'lookback': 15}, {'lookback': 20}, {'lookback': 25}],
    'mom_breakout': [
        {'period': 10, 'threshold': 0.03},
        {'period': 20, 'threshold': 0.05},
        {'period': 30, 'threshold': 0.08},
    ],
}

# 过滤器组合（有经济含义，不暴力枚举）
FILTER_SETS: list[list[str]] = [
    [],
    ['turnover'],
    ['st'],
    ['st', 'liquidity'],
    ['st', 'turnover'],
]


def _entry_with(entry: EntryFunc, overrides: dict) -> EntryFunc:
    """生成带覆盖参数的 entry 副本（参数冻结用）。"""
    from dataclasses import replace

    meta = replace(entry.meta, params={**entry.meta.params, **overrides})
    return replace(entry, meta=meta)


def _train_score(trades: list[Trade]) -> float:
    """训练段评分：平均收益 × sqrt(样本量)（兼顾 edge 与置信度）。"""
    if len(trades) < MIN_TRAIN_TRADES:
        return float('-inf')
    rets = [t.ret for t in trades]
    mean = sum(rets) / len(rets)
    return mean * (len(rets) ** 0.5)


def _run_window(ctx_args: dict, train: tuple[str, str], valid: tuple[str, str]) -> dict:
    from .simulate import ScanContext

    train_trades = run_scan(ScanContext(**ctx_args), start=train[0], end=train[1])
    best_params, best_score = {}, float('-inf')
    entry = ctx_args['entry']
    for overrides in ENTRY_GRID.get(entry.meta.name, [{}]):
        frozen = _entry_with(entry, overrides)
        trial_args = {**ctx_args, 'entry': frozen}
        trades = run_scan(ScanContext(**trial_args), start=train[0], end=train[1])
        score = _train_score(trades)
        if score > best_score:
            best_score, best_params = score, overrides
    frozen = _entry_with(entry, best_params)
    valid_trades = run_scan(ScanContext(**{**ctx_args, 'entry': frozen}), start=valid[0], end=valid[1])
    return {
        'bestParams': best_params,
        'trainScore': None if best_score == float('-inf') else round(best_score, 6),
        'validTrades': [t.as_dict() for t in valid_trades],
        'validSummary': summarize(valid_trades),
    }


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='第二轮 walk-forward 组合验证')
    parser.add_argument('--codes', required=True)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--max-positions', type=int, default=5)
    parser.add_argument('--train-years', type=int, default=2)
    parser.add_argument('--valid-years', type=int, default=1)
    args = parser.parse_args()

    from datetime import date

    from .round1_signal_scan import load_pool_frames

    codes = [c.strip() for c in args.codes.split(',') if c.strip()]
    frames = load_pool_frames(codes, args.start, args.end)
    if not frames:
        print('❌ 股票池无任何数据')
        return 1

    windows = walk_forward_windows(
        date.fromisoformat(args.start), date.fromisoformat(args.end),
        train_years=args.train_years, valid_years=args.valid_years,
    )
    print(f'{len(frames)} 支标的，{len(windows)} 个 walk-forward 窗口')

    base_filters = {'st': [FILTERS['st']], 'turnover': [FILTERS['turnover']], 'liquidity': [FILTERS['liquidity']]}
    report: dict = {'start': args.start, 'end': args.end, 'windows': [w.as_dict() for w in windows], 'combos': {}}
    n_combos = 0
    for entry_name, entry in ENTRIES.items():
        for filter_names in FILTER_SETS:
            filters: list[FilterFunc] = []
            for fname in filter_names:
                filters.extend(base_filters[fname])
            for exit_name in EXITS:
                combo_id = f'{entry_name}|{"+".join(filter_names) or "none"}|{exit_name}'
                ctx_args = {
                    'frames': frames,
                    'entry': entry,
                    'filters': filters,
                    'exit_fn': EXITS[exit_name],
                    'max_positions': args.max_positions,
                }
                window_results = []
                for window in windows:
                    window_results.append(
                        _run_window(ctx_args, (window.train_start.isoformat(), window.train_end.isoformat()),
                                    (window.valid_start.isoformat(), window.valid_end.isoformat()))
                    )
                    print(f'  {combo_id} 窗口 {window.valid_start.year} 完成')
                # 拼接所有验证段交易形成样本外曲线
                oos_trades = [t for wr in window_results for t in wr['validTrades']]
                rets = [t['ret'] for t in oos_trades]
                oos_curve = 1.0
                for r in rets:
                    oos_curve *= 1 + r
                wins = sum(1 for r in rets if r > 0)
                pval = binom_two_sided_pvalue(wins, len(rets)) if rets else 1.0
                report['combos'][combo_id] = {
                    'windows': window_results,
                    'oos': {
                        'nTrades': len(rets),
                        'winRate': round(wins / len(rets), 4) if rets else 0,
                        'totalRet': round(oos_curve - 1, 6),
                        'pValue': round(pval, 6),
                    },
                }
                n_combos += 1

    # 多假设校正：对全部组合的 p 值做 BH
    combo_ids = list(report['combos'])
    pvals = [report['combos'][cid]['oos']['pValue'] for cid in combo_ids]
    adjusted = benjamini_hochberg(pvals)
    for cid, p in zip(combo_ids, adjusted):
        report['combos'][cid]['oos']['pValueBH'] = round(p, 6)
    report['nCombos'] = n_combos

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / 'round2.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'✅ {n_combos} 个组合完成，结果已写入 {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

