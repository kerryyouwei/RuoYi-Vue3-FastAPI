"""方案A · ETF动量轮动 本地冒烟测试。

运行：
  PYTHONIOENCODING=utf-8 python youw_test/test_etf_rotation.py

说明：
- 主时钟使用腾讯前复权 510300，避免 QUANTAXIS 指数数据依赖；
- UNIVERSE 中的 17 只 ETF 也走腾讯前复权加载器；
- live_start 后才开始执行策略，前面只用于 warmup。
"""

import sys
from datetime import datetime
from pathlib import Path

import backtrader as bt

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from youw_test.strategies.etf_data import fetch_etf_daily
from youw_test.strategies.etf_rotation import UNIVERSE, Strategy


def load_feed(cerebro: bt.Cerebro, code: str, start: str, end: str) -> bool:
    print(f"loading {code} ...", flush=True)
    data = fetch_etf_daily(code, start, end)
    if data is None or data.empty:
        print(f"  WARN: {code} no data")
        return False
    cerebro.adddata(bt.feeds.PandasData(dataname=data), name=code)
    print(f"  rows={len(data)}, {data.index.min()} ~ {data.index.max()}")
    return True


def main() -> int:
    start = "2024-06-01"
    live_start = "2025-01-01"
    end = "2025-09-26"

    cerebro = bt.Cerebro()
    if not load_feed(cerebro, "510300", start, end):
        print("FAIL: master clock 510300 has no data")
        return 2

    loaded = 0
    for code in UNIVERSE:
        loaded += int(load_feed(cerebro, code, start, end))
    print(f"universe feeds loaded: {loaded}/{len(UNIVERSE)}")
    if loaded < 10:
        print("FAIL: too few ETF feeds loaded; check network or codes")
        return 2

    live_start_date = datetime.strptime(live_start, "%Y-%m-%d").date()

    class LiveStartStrategy(Strategy):
        def next(self):
            if self.datas[0].datetime.date(0) < live_start_date:
                return
            super().next()

    cerebro.addstrategy(
        LiveStartStrategy,
        mom_period=20,
        regime_ma_period=60,
        rotate_gain=0.05,
        cyb_edge=0.06,
        stop_ratio=0.92,
        cooldown_days=20,
    )
    cerebro.broker.setcash(50000.0)

    class EtfCommissionInfo(bt.CommissionInfo):
        params = (
            ("commission", 0.0003),
            ("stamp_duty", 0.0),
            ("min_commission", 0.0),
        )

        def _getcommission(self, size, price, pseudoexec):
            return abs(size) * price * self.p.commission

    cerebro.broker.addcommissioninfo(EtfCommissionInfo())

    result = cerebro.run()
    strategy = result[0]
    final_value = cerebro.broker.getvalue()
    records = strategy.execution_records

    print("\n===== smoke result =====")
    print(f"final_value={final_value:.2f}")
    print(f"execution_records={len(records)}")
    print(f"last_records={records[-5:]}")

    assert final_value > 0
    assert isinstance(records, list)
    assert records, "strategy has no execution records after live_start"
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())