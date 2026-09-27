"""
简单的均线交叉策略回测
策略: MA5上穿MA20买入，下穿卖出
"""
import pandas as pd
import QUANTAXIS as QA
from QUANTAXIS.QIFI import QIFI_Account

# 1. 准备数据
df = QA.QA_fetch_get_stock_day(
    'baostock', '000001', '2023-01-01', '2024-01-31'
)
if df is None or df.empty:
    raise RuntimeError("未能获取行情数据，请检查网络连接。")
data = QA.QA_DataStruct_Stock_day(df.set_index(['date', 'code']))

# 2. 计算指标
ma5 = data.data['close'].rolling(5).mean()
ma20 = data.data['close'].rolling(20).mean()

# 3. 生成信号
signal = pd.DataFrame(index=data.data.index)
signal['ma5'] = ma5
signal['ma20'] = ma20
signal['position'] = 0

# 金叉买入，死叉卖出
signal.loc[ma5 > ma20, 'position'] = 1
signal.loc[ma5 < ma20, 'position'] = 0

# 4. 创建账户
account = QIFI_Account(
    username="test_strategy",
    password="test",
    model="BACKTEST",
    init_cash=100000,
    nodatabase=True
)
account.create_backtestaccount()

# 5. 模拟交易
position_amount = 0
current_date = None
for date, row in signal.iterrows():
    trade_date = date[0] if isinstance(date, tuple) else date
    price = data.data.loc[date, 'close']

    if current_date is not None and trade_date != current_date:
        account.settle()
    current_date = trade_date
    account.on_price_change('000001', price, str(trade_date))

    # 买入信号
    if row['position'] == 1 and position_amount == 0:
        # 计算可买数量（100股整数倍）
        amount = int(account.available / price / 100) * 100
        if amount > 0:
            order = account.send_order(
                code='000001',
                amount=amount,
                price=price,
                towards=QA.ORDER_DIRECTION.BUY,
                datetime=str(trade_date)
            )
            if order:
                account.make_deal(order)
                position_amount = amount
                print(f"{trade_date}: 买入 {amount}股 @ {price:.2f}元")

    # 卖出信号
    elif row['position'] == 0 and position_amount > 0:
        # 获取当前持仓
        amount = position_amount
        if amount > 0:
            order = account.send_order(
                code='000001',
                amount=amount,
                price=price,
                towards=QA.ORDER_DIRECTION.SELL,
                datetime=str(trade_date)
            )
            if order:
                account.make_deal(order)
                position_amount = 0
                print(f"{trade_date}: 卖出 {amount}股 @ {price:.2f}元")

# 6. 输出结果
print("\n" + "=" * 50)
print("回测结果")
print("=" * 50)
final_equity = account.balance
position_value = sum(
    item.volume_long * item.last_price for item in account.positions.values()
)
print(f"初始资金: {100000:.2f}元")
print(f"最终总权益: {final_equity:.2f}元")
print(f"可用现金: {account.available:.2f}元")
print(f"持仓市值: {position_value:.2f}元")
print(f"总盈亏: {final_equity - 100000:.2f}元")
print(f"收益率: {(final_equity / 100000 - 1) * 100:.2f}%")
print("=" * 50)
