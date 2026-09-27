"""RSI 超卖买入、超买卖出策略。"""

import backtrader as bt

from .base import BaseStrategy


class Strategy(BaseStrategy):
    params = (
        ("period", 14),
        ("oversold", 30),
        ("overbought", 70),
    )

    def __init__(self):
        super().__init__()
        self.rsi = bt.indicators.RSI_Safe(
            self.data.close, period=self.p.period
        )

    def next(self):
        if self.rsi[0] < self.p.oversold:
            self.buy_position(f"RSI={self.rsi[0]:.2f} 进入超卖区")
        elif self.rsi[0] > self.p.overbought:
            self.close_position(f"RSI={self.rsi[0]:.2f} 进入超买区")

