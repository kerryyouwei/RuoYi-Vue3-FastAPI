"""
数据可视化
"""

import QUANTAXIS as QA
import matplotlib.pyplot as plt

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 获取数据
df = QA.QA_fetch_get_stock_day('tdx', '000001', '2023-01-01', '2024-01-31')
data = QA.QA_DataStruct_Stock_day(df.set_index(['date', 'code']))
x = data.data.index.get_level_values('date')

# 创建图表
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

# 价格走势
ax1.plot(x, data.data['close'], label='收盘价')
ax1.plot(x, data.data['close'].rolling(20).mean(), label='MA20')
ax1.set_title('平安银行股价走势')
ax1.set_ylabel('价格 (元)')
ax1.legend()
ax1.grid(True)

# 成交量
ax2.bar(x, data.data['volume'], alpha=0.5)
ax2.set_title('成交量')
ax2.set_ylabel('成交量 (股)')
ax2.grid(True)

plt.tight_layout()
plt.savefig('stock_analysis.png')
print("\n✅ 图表已保存至 stock_analysis.png")
