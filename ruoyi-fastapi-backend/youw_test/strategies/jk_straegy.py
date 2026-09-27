"""聚宽 MA5 突破策略的本地框架改写版本。"""

import math

import backtrader as bt

from .base import BaseStrategy


class Strategy(BaseStrategy):
    params = (
        ("ma_period", 5),
        ("breakout_ratio", 1.01),
        ("max_trade_count", 10),
        ("all_in", True),
    )

    def __init__(self):
        super().__init__()
        self.ma5 = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.ma_period
        )
        self.completed_buy_count = 0
        self.completed_sell_count = 0

    def next(self):
        if not math.isnan(self.ma5[0]):
            self.log(
                f"close={self.data.close[0]:.2f}, "
                f"MA5={self.ma5[0]:.2f}"
            )

        if self.data.close[0] > self.p.breakout_ratio * self.ma5[0]:
            if self.completed_buy_count < self.p.max_trade_count:
                self.buy_position("价格高于 MA5 1%")
        elif self.data.close[0] < self.ma5[0]:
            if self.completed_sell_count < self.p.max_trade_count:
                self.close_position("价格低于 MA5")

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.completed_buy_count += 1
            else:
                self.completed_sell_count += 1
        super().notify_order(order)
