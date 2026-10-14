"""
获取实时行情数据
"""

# QUANTAXIS 的统一入口会先从 MongoDB 读取 TDX IP 配置；如果 MongoDB 不可用，
# 这里直接使用底层 TDX 接口并指定可用行情服务器，绕开这一步。
from QUANTAXIS.QAFetch.QATdx import QA_fetch_get_stock_realtime

realtime = QA_fetch_get_stock_realtime(
    code=['000001', '000002', '600000'],
    ip='shtdx.gtjas.com',
    port=7709,
)

print("\n实时行情:")
if realtime is None or realtime.empty:
    print("未获取到实时行情数据")
else:
    realtime = realtime.reset_index().rename(columns={'vol': 'volume'})
    print(realtime[['code', 'price', 'bid1', 'ask1', 'volume']])
