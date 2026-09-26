"""策略插件公共基类。"""

import backtrader as bt


class BaseStrategy(bt.Strategy):
    params = (("trade_size", 1000),)

    def __init__(self):
        self.pending_order = None

    def log(self, message):
        current_date = self.datas[0].datetime.date(0).isoformat()
        print(f"[{current_date}] {message}")

    def buy_position(self, reason):
        if self.pending_order is not None or self.position:
            return
        self.log(
            f"买入信号({reason}): close={self.data.close[0]:.2f}, "
            f"数量={self.p.trade_size}"
        )
        self.pending_order = self.buy(size=self.p.trade_size)

    def close_position(self, reason):
        if self.pending_order is not None or not self.position:
            return
        self.log(
            f"卖出信号({reason}): close={self.data.close[0]:.2f}, "
            f"数量={self.position.size}"
        )
        self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            side = "买入" if order.isbuy() else "卖出"
            self.log(
                f"{side}成交: price={order.executed.price:.2f}, "
                f"size={abs(order.executed.size)}, "
                f"value={abs(order.executed.value):.2f}, "
                f"commission={order.executed.comm:.2f}, "
                f"cash={self.broker.getcash():.2f}, "
                f"account_value={self.broker.getvalue():.2f}"
            )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            side = "买入" if order.isbuy() else "卖出"
            self.log(f"{side}订单未完成: status={order.getstatusname()}")

        if order is self.pending_order:
            self.pending_order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(
                f"交易结束: gross_pnl={trade.pnl:.2f}, "
                f"net_pnl={trade.pnlcomm:.2f}"
            )

