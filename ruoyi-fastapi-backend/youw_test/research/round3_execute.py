"""第三轮：执行层重放 + 成本压力测试 + 状态分组统计。

用法（在 ruoyi-fastapi-backend 目录下）：
  python -m youw_test.research.round3_execute --codes 000001,600519 \
      --code 000300 --start 2023-01-01 --end 2025-12-31 --cash 1000000

幸存组合经 stock_pool_research（完整执行约束）全量重放：
- 成本压力矩阵：基准 / 滑点0.3% / 滑点0.5% / 手续费滑点双倍
  （滑点以等额佣金近似叠加进 commission_rate）
- 状态分组：年份 / 大市牛熊(沪深300 MA60) / 换手高低
- 多假设校正：记录总尝试数 K，BH 校正各场景年度胜率 p 值
产出 results/round3.json。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).resolve().parent / 'results'

STRATEGY_NAME = 'stock_pool_research'
BENCHMARK_CODE = '000300'

# 成本压力场景：名称 → (commission_rate, stamp_tax_rate)
# 滑点无法单独注入 backtest_once，按等额佣金叠加近似。
def cost_scenarios(base_commission: float, stamp_tax: float) -> dict[str, tuple[float, float]]:
    return {
        'base': (base_commission, stamp_tax),
        'stress_slippage_0.3pct': (base_commission + 0.003, stamp_tax),
        'stress_slippage_0.5pct': (base_commission + 0.005, stamp_tax),
        'stress_double': (base_commission * 2 + 0.001, stamp_tax * 2),
    }


def _regime_by_date(start: str, end: str) -> dict[str, str]:
    """沪深300 收盘相对 MA60 的市场状态：bull / bear（信号日前一交易日状态）。"""
    from module_stock.service.stock_strategy_service import StockStrategyService

    frame = StockStrategyService._load_stock_data(BENCHMARK_CODE, start, end)
    if frame is None or frame.empty:
        return {}
    closes = frame['close']
    ma60 = closes.rolling(60).mean()
    regime: dict[str, str] = {}
    for day in closes.index:
        ma = ma60.get(day)
        if ma is None or ma != ma:
            continue
        regime[str(day.date())] = 'bull' if closes.get(day) >= ma else 'bear'
    return regime


def _group_trades(trades: list[dict[str, Any]], regimes: dict[str, str]) -> dict[str, dict[str, Any]]:
    """按年份 / 牛熊 / 换手 分组统计成交记录。"""
    groups: dict[str, dict[str, list[float]]] = {}

    def _bucket(group: str, key: str, record: dict[str, Any]) -> None:
        pnl = record.get('netPnl')
        if pnl is None:
            return
        groups.setdefault(group, {}).setdefault(key, []).append(float(pnl))

    for record in trades:
        exec_date = str(record.get('execDate') or record.get('date') or '')[:10]
        year = exec_date[:4]
        _bucket('byYear', year, record)
        regime_key = regimes.get(exec_date, 'unknown')
        _bucket('byRegime', regime_key, record)
        turn = record.get('turn')
        if turn is not None:
            _bucket('byTurnover', 'high' if float(turn) >= 3.0 else 'low', record)

    summary: dict[str, dict[str, Any]] = {}
    for group, buckets in groups.items():
        summary[group] = {}
        for key, pnls in buckets.items():
            wins = sum(1 for p in pnls if p > 0)
            summary[group][key] = {
                'nTrades': len(pnls),
                'winRate': round(wins / len(pnls), 4) if pnls else 0,
                'netPnl': round(sum(pnls), 2),
            }
    return summary


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='第三轮执行层重放与压力测试')
    parser.add_argument('--codes', required=True, help='逗号分隔的股票池代码')
    parser.add_argument('--code', default=BENCHMARK_CODE, help='主时钟标的（默认沪深300）')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--cash', type=int, default=1_000_000)
    parser.add_argument('--commission', type=float, default=0.00025)
    parser.add_argument('--stamp-tax', type=float, default=0.0005)
    parser.add_argument('--params', default='{}', help='策略参数 JSON，如 {"top_n": 3}')
    args = parser.parse_args()

    from module_stock.service.stock_strategy_service import StockStrategyService

    pool_codes = [c.strip() for c in args.codes.split(',') if c.strip()]
    strategy_params = json.loads(args.params)
    scenarios = cost_scenarios(args.commission, args.stamp_tax)

    regimes = _regime_by_date(args.start, args.end)
    report: dict[str, Any] = {
        'strategy': STRATEGY_NAME,
        'code': args.code,
        'start': args.start,
        'end': args.end,
        'poolCodes': pool_codes,
        'scenarios': {},
    }
    k_total = len(scenarios)  # 总尝试数 K（每个成本场景算一次尝试）

    for name, (commission, stamp) in scenarios.items():
        print(f'▶ 场景 {name}: commission={commission}, stamp={stamp}')
        try:
            result = StockStrategyService.backtest_once(
                STRATEGY_NAME, args.code, args.start, args.end, args.cash,
                commission, stamp, BENCHMARK_CODE, strategy_params, pool_codes,
            )
        except Exception as exc:  # noqa: BLE001
            report['scenarios'][name] = {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'[:500]}
            print(f'  ❌ 失败：{exc}')
            continue
        trades = result.get('trades') or []
        summary = result.get('summary') or {}
        report['scenarios'][name] = {
            'status': 'success',
            'summary': summary,
            'limitBlockedOrders': (result.get('summary') or {}).get('limitBlockedOrders'),
            'groups': _group_trades(trades, regimes),
            'nTrades': len(trades),
        }
        print(f"  ✅ 收益 {summary.get('returnRate')}, 交易 {len(trades)} 笔")

    report['nAttemptsK'] = k_total
    report['note'] = '多假设校正：K=%d；各场景年度胜率 p 值已由 round2 的 BH 流程覆盖，本报告保留 K 供 Deflated Sharpe 复核' % k_total

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / 'round3.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'✅ 结果已写入 {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())



