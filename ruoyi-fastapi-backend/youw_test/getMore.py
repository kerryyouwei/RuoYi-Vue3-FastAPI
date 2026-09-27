"""
获取多只股票的历史数据
"""

import QUANTAXIS as QA

# 股票代码列表
stocks = ['000001', '000002', '600000']

# 批量获取数据
for code in stocks:
    df = QA.QA_fetch_get_stock_day(
        package='tdx',     
        code=code,
        start='2024-01-01',
        end='2024-01-10'
    )

    if df is None or df.empty:
        print(f"\n股票 {code}: 未获取到行情数据")
        continue

    # 使用QA数据结构
    data = QA.QA_DataStruct_Stock_day(df.set_index(['date', 'code']))

    print(f"\n股票 {code}:")
    print(f"  交易天数: {len(data.data)}")
    print(f"  涨跌幅: {data.data['close'].pct_change().mean() * 100:.2f}%")
