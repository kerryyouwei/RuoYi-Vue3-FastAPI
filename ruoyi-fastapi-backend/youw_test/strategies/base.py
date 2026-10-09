"""策略插件公共基类。"""

import backtrader as bt

class BaseStrategy(bt.Strategy):
    params = (
        ("trade_size", 1000),
        ("all_in", False),
    )

    def __init__(self):
        self.pending_order = None
        self.execution_records = []
        self.signal = '持有'
        self.signal_reason = ''

    def log(self, message):
        current_date = self.datas[0].datetime.date(0).isoformat()
        print(f"[{current_date}] {message}")

    def buy_position(self, reason):
        self.signal = '买入'
        self.signal_reason = reason
        # 不加仓：已有持仓或挂单时，新的买入信号直接忽略。
        if self.pending_order is not None or self.position:
            self.log(f"已有持仓或挂单，忽略买入信号({reason})")
            return
        if self.p.all_in:
            size = self._max_buy_size()
            if size <= 0:
                self.log(
                    f"买入信号({reason}): close={self.data.close[0]:.2f}, "
                    "可用资金不足，跳过买入"
                )
                return
            self.log(
                f"买入信号({reason}): close={self.data.close[0]:.2f}, "
                f"数量={size}，全部可用资金"
            )
            self.pending_order = self.buy(size=size)
        else:
            self.log(
                f"买入信号({reason}): close={self.data.close[0]:.2f}, "
                f"数量={self.p.trade_size}"
            )
            self.pending_order = self.buy(size=self.p.trade_size)

    def _max_buy_size(self):
        price = float(self.data.close[0])
        if price <= 0:
            return 0
        cash = float(self.broker.getcash())
        # A股买入必须按手申报，一手是 100 股。
        size = int(cash / price // 100 * 100)
        commission_info = self.broker.getcommissioninfo(self.data)
        while size > 0:
            total_cost = size * price + commission_info.getcommission(size, price)
            if total_cost <= cash:
                break
            size -= 100
        return size

    def close_position(self, reason):
        self.signal = '卖出'
        self.signal_reason = reason
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
                f"value={abs(order.executed.size * order.executed.price):.2f}, "
                f"commission={order.executed.comm:.2f}, "
                f"cash={self.broker.getcash():.2f}, "
                f"account_value={self.broker.getvalue():.2f}"
            )
            self.execution_records.append(
                {
                    "date": self.datas[0].datetime.date(0).isoformat(),
                    "code": order.data._name,
                    "side": side,
                    "price": round(order.executed.price, 4),
                    "size": abs(order.executed.size),
                    # 卖出时 Backtrader 的 order.executed.value 不是本笔卖出成交额，
                    # 这里统一按 成交价 × 成交数量 记录，避免卖出金额显示成买入成本。
                    "value": round(abs(order.executed.size * order.executed.price), 4),
                    "commission": round(order.executed.comm, 4),
                    "cash": round(self.broker.getcash(), 4),
                    "accountValue": round(self.broker.getvalue(), 4),
                    "grossPnl": None,
                    "netPnl": None,
                }
            )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            side = "买入" if order.isbuy() else "卖出"
            self.log(f"{side}订单未完成: status={order.getstatusname()}")

        # Backtrader 可能在部分场景下通知的不是同一个对象，
        # 这里只要到达终态就清掉唯一挂单，避免后续信号被卡住。
        if order.status in [
            order.Completed,
            order.Canceled,
            order.Margin,
            order.Rejected,
        ]:
            self.pending_order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            for record in reversed(self.execution_records):
                if record["side"] == "卖出" and record["netPnl"] is None:
                    record["grossPnl"] = round(trade.pnl, 4)
                    record["netPnl"] = round(trade.pnlcomm, 4)
                    break
            self.log(
                f"交易结束: gross_pnl={trade.pnl:.2f}, "
                f"net_pnl={trade.pnlcomm:.2f}"
            )
