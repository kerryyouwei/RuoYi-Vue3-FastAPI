"""
获取实时行情数据
"""

import QUANTAXIS as QA

# 获取股票实时行情
realtime = QA.QA_fetch_get_stock_realtime(
    package='tdx',
    code=['000001', '000002', '600000']
)

print("\n实时行情:")
if realtime is None or realtime.empty:
    print("未获取到实时行情数据")
else:
    realtime = realtime.reset_index().rename(columns={'vol': 'volume'})
    print(realtime[['code', 'price', 'bid1', 'ask1', 'volume']])
