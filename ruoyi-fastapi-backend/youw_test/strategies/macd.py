"""MACD 金叉与死叉策略。"""

import backtrader as bt

from .base import BaseStrategy


class Strategy(BaseStrategy):
    params = (
        ("fast_period", 12),
        ("slow_period", 26),
        ("signal_period", 9),
    )

    def __init__(self):
        super().__init__()
        macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.fast_period,
            period_me2=self.p.slow_period,
            period_signal=self.p.signal_period,
        )
        self.crossover = bt.indicators.CrossOver(macd.macd, macd.signal)

    def next(self):
        if self.crossover > 0:
            self.buy_position("MACD 金叉")
        elif self.crossover < 0:
            self.close_position("MACD 死叉")

