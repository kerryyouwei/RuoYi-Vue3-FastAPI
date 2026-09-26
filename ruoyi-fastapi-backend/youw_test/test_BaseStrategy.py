"""使用 Backtrader 执行简单的均线交叉回测。"""

import pandas as pd

import QUANTAXIS as QA

try:
    import backtrader as bt
except ImportError as exc:
    raise SystemExit(
        "缺少 backtrader，请先运行: python -m pip install backtrader"
    ) from exc

from strategies import load_strategy

STRATEGY_NAME = "ma"  # 可选: ma、macd、turtle、rsi、my_strategy
STRATEGY_PARAMS = {"trade_size": 1000}


def load_stock_data(code, start, end):
    stock_data = QA.QA_fetch_stock_day_adv(code, start, end)
    if stock_data is None or stock_data.data.empty:
        print(
            f"本地数据库无行情数据: code={code}, "
            f"start={start}, end={end}"
        )
        return None

    data = stock_data.data.reset_index().copy()
    data["datetime"] = pd.to_datetime(data["date"])
    data = data.set_index("datetime")
    columns = ["open", "high", "low", "close", "volume"]
    data[columns] = data[columns].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=columns)
    if data.empty:
        print(f"本地数据库中 {code} 的有效行情数据为空")
        return None

    return data[columns].sort_index()


def run_backtest():
    code = "000001"
    start = "2023-01-01"
    end = "2024-01-31"
    initial_cash = 100000
    commission_rate = 3 / 10000

    price_data = load_stock_data(code, start, end)
    if price_data is None:
        return

    feed = bt.feeds.PandasData(dataname=price_data)
    strategy_class = load_strategy(STRATEGY_NAME)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class, **STRATEGY_PARAMS)
    cerebro.adddata(feed, name=code)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission_rate)

    starting_value = cerebro.broker.getvalue()
    cerebro.run()
    ending_value = cerebro.broker.getvalue()
    profit_rate = (ending_value / starting_value) - 1

    print(f"策略插件: {STRATEGY_NAME}")
    print(f"初始资金: {starting_value:.2f}")
    print(f"期末资金: {ending_value:.2f}")
    print(f"手续费率: {commission_rate * 10000:.0f}‱")
    print(f"收益率: {profit_rate * 100:.2f}%")


if __name__ == "__main__":
    run_backtest()
