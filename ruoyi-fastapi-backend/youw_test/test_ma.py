"""
计算技术指标
"""

import QUANTAXIS as QA
import pandas as pd

# 获取数据
df = QA.QA_fetch_get_stock_day('tdx','000001', '2023-01-01', '2024-01-31')
data = QA.QA_DataStruct_Stock_day(df.set_index(['date', 'code']))

# 计算均线
ma5 = data.data['close'].rolling(5).mean()
ma10 = data.data['close'].rolling(10).mean()
ma20 = data.data['close'].rolling(20).mean()

print("\n均线系统 (最近5天):")
print(pd.DataFrame({
    '日期': data.data.index[-5:],
    '收盘价': data.data['close'][-5:].values,
    'MA5': ma5[-5:].values,
    'MA10': ma10[-5:].values,
    'MA20': ma20[-5:].values,
}))

# 使用QA内置指标
from QUANTAXIS.QAIndicator import QA_indicator_MA, QA_indicator_MACD

# 计算MACD
macd_df = QA_indicator_MACD(data.data)
print("\nMACD指标 (最近5天):")
print(macd_df.tail())
