"""组合策略增强数据 feed：OHLCV + 可选增强字段。

增强字段（Baostock 后复权数据）缺失时对应 line 全为 NaN，
策略端按降级规则推导（见 stock_pool_research.py）。
"""

import backtrader as bt


class StockPoolFeed(bt.feeds.PandasData):
    """OHLCV + amount/tradestatus/isst/preclose/turn 增强 lines。

    用法：有增强列时传对应列名；没有时保持 None（line 为 NaN）。
    """

    lines = ('amount', 'tradestatus', 'isst', 'preclose', 'turn')

    params = (
        ('amount', None),
        ('tradestatus', None),
        ('isst', None),
        ('preclose', None),
        ('turn', None),
    )
