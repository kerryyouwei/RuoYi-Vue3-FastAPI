"""简单移动平均线交叉策略。"""

import backtrader as bt

from .base import BaseStrategy


class Strategy(BaseStrategy):
    params = (
        ("short_period", 5),
        ("long_period", 20),
    )

    def __init__(self):
        super().__init__()
        short_ma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.short_period
        )
        long_ma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.long_period
        )
        self.crossover = bt.indicators.CrossOver(short_ma, long_ma)

    def next(self):
        if self.crossover > 0:
            self.buy_position("短期均线上穿长期均线")
        elif self.crossover < 0:
            self.close_position("短期均线下穿长期均线")

