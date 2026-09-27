"""
使用 MongoDB 中的 QUANTAXIS 日线数据执行均线交叉回测。
"""

from dataclasses import dataclass

import QUANTAXIS as QA


@dataclass
class BacktestResult:
    profit_rate: float
    final_equity: float
    cash: float
    position_value: float
    trades: list


class MyStrategy:
    def __init__(
        self,
        code='002594',
        start='2025-01-01',
        end='2026-01-31',
        init_cash=100000,
        ma_short=5,
        ma_long=20,
        commission_rate=0.0003,
    ):
        self.code = code
        self.start = start
        self.end = end
        self.init_cash = init_cash
        self.ma_short = ma_short
        self.ma_long = ma_long
        self.commission_rate = commission_rate

    def load_data(self):
        data = QA.QA_fetch_stock_day_adv(
            self.code,
            self.start,
            self.end,
        )
        if data is None or data.data.empty:
            raise RuntimeError(
                "MongoDB 中没有对应行情数据，请先从 Baostock 获取并写入 "
                "quantaxis.stock_day。"
            )
        return data.data.sort_index().copy()

    def run(self):
        bars = self.load_data()
        bars['ma_short'] = bars['close'].rolling(self.ma_short).mean()
        bars['ma_long'] = bars['close'].rolling(self.ma_long).mean()

        holding_signal = bars['ma_short'] > bars['ma_long']
        bars['buy_signal'] = holding_signal & ~holding_signal.shift(
            1, fill_value=False
        )
        bars['sell_signal'] = ~holding_signal & holding_signal.shift(
            1, fill_value=False
        )

        cash = float(self.init_cash)
        position_amount = 0
        trades = []

        for index, bar in bars.iterrows():
            trade_date = index[0] if isinstance(index, tuple) else index
            price = float(bar['close'])

            if bar['buy_signal'] and position_amount == 0:
                amount = int(
                    cash / (price * (1 + self.commission_rate)) / 100
                ) * 100
                if amount > 0:
                    commission = amount * price * self.commission_rate
                    cash -= amount * price + commission
                    position_amount = amount
                    trades.append(('BUY', trade_date, amount, price))
                    print(f"{trade_date}: 买入 {amount}股 @ {price:.2f}元")

            elif bar['sell_signal'] and position_amount > 0:
                commission = position_amount * price * self.commission_rate
                cash += position_amount * price - commission
                trades.append(('SELL', trade_date, position_amount, price))
                print(
                    f"{trade_date}: 卖出 {position_amount}股 @ {price:.2f}元"
                )
                position_amount = 0

        final_price = float(bars.iloc[-1]['close'])
        position_value = position_amount * final_price
        final_equity = cash + position_value

        return BacktestResult(
            profit_rate=final_equity / self.init_cash - 1,
            final_equity=final_equity,
            cash=cash,
            position_value=position_value,
            trades=trades,
        )


strategy = MyStrategy()
result = strategy.run()

print("\n" + "=" * 50)
print("回测结果")
print("=" * 50)
print(f"最终权益: {result.final_equity:.2f}元")
print(f"可用现金: {result.cash:.2f}元")
print(f"持仓市值: {result.position_value:.2f}元")
print(f"交易次数: {len(result.trades)}")
print(f"收益率: {result.profit_rate * 100:.2f}%")
