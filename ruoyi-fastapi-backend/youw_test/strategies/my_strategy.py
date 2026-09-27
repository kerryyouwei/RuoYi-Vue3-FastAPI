"""自定义策略模板：双 EMA 交叉。"""

import backtrader as bt

from .base import BaseStrategy


class Strategy(BaseStrategy):
    params = (
        ("fast_period", 10),
        ("slow_period", 30),
    )

    def __init__(self):
        super().__init__()
        fast_ema = bt.indicators.ExponentialMovingAverage(
            self.data.close, period=self.p.fast_period
        )
        slow_ema = bt.indicators.ExponentialMovingAverage(
            self.data.close, period=self.p.slow_period
        )
        self.crossover = bt.indicators.CrossOver(fast_ema, slow_ema)

    def next(self):
        if self.crossover > 0:
            self.buy_position("快速 EMA 上穿慢速 EMA")
        elif self.crossover < 0:
            self.close_position("快速 EMA 下穿慢速 EMA")

