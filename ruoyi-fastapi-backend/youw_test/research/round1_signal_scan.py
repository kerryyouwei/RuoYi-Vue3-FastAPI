"""第一轮：裸信号广筛。

用法（在 ruoyi-fastapi-backend 目录下）：
  python -m youw_test.research.round1_signal_scan --codes 000001,600519 \
      --start 2019-01-01 --end 2025-12-31

对每个 entry 函数在固定试验条件下（10%名义仓位、10个交易日出场、基准成本）
统计样本量/胜率/跨年一致性/跨股票覆盖，产出 results/round1.json。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / 'results'


def load_pool_frames(codes: list[str], start: str, end: str) -> dict:
    """加载股票池日线（优先后复权增强数据，失败回退现有 OHLCV）。"""
    from module_stock.service.stock_strategy_service import StockStrategyService

    frames = {}
    for code in codes:
        frame = StockStrategyService._load_stock_enriched_data(code, start, end)
        if frame is None:
            frame = StockStrategyService._load_stock_data(code, start, end)
        if frame is None or frame.empty:
            print(f'⚠️ {code} 无数据，跳过')
            continue
        frame = frame.copy()
        frame.attrs['code'] = code
        frames[code] = frame
    return frames


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='第一轮裸信号广筛')
    parser.add_argument('--codes', required=True, help='逗号分隔的股票代码')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--max-positions', type=int, default=5)
    args = parser.parse_args()

    from .funcs.entry import ENTRIES
    from .funcs.filter import FILTERS
    from .funcs.exit import EXITS
    from .simulate import ScanContext, run_scan, summarize

    codes = [c.strip() for c in args.codes.split(',') if c.strip()]
    frames = load_pool_frames(codes, args.start, args.end)
    if not frames:
        print('❌ 股票池无任何数据')
        return 1
    print(f'加载 {len(frames)} 支标的，区间 {args.start} ~ {args.end}')

    base_filters = [FILTERS['st'], FILTERS['liquidity']]
    report = {'start': args.start, 'end': args.end, 'codes': list(frames), 'entries': {}}
    for name, entry in ENTRIES.items():
        ctx = ScanContext(
            frames=frames,
            entry=entry,
            filters=base_filters,
            exit_fn=EXITS['fixed_days'],
            max_positions=args.max_positions,
        )
        trades = run_scan(ctx, start=args.start, end=args.end)
        stats = summarize(trades)
        report['entries'][name] = stats
        n = stats.get('nTrades', 0)
        win = stats.get('winRate', 0)
        print(f'  {name}: {n} 笔, 胜率 {win:.1%}')

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / 'round1.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'✅ 结果已写入 {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

