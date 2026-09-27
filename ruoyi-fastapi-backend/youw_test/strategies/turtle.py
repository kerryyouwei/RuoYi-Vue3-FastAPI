"""海龟通道突破策略。"""

import backtrader as bt

from .base import BaseStrategy


class Strategy(BaseStrategy):
    params = (
        ("entry_period", 20),
        ("exit_period", 10),
    )

    def __init__(self):
        super().__init__()
        self.entry_high = bt.indicators.Highest(
            self.data.high(-1), period=self.p.entry_period
        )
        self.exit_low = bt.indicators.Lowest(
            self.data.low(-1), period=self.p.exit_period
        )

    def next(self):
        if self.data.close[0] > self.entry_high[0]:
            self.buy_position("突破前期高点")
        elif self.data.close[0] < self.exit_low[0]:
            self.close_position("跌破退出通道")

