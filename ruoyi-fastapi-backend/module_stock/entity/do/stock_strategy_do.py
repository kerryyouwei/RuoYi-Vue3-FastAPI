from sqlalchemy import JSON, BigInteger, Column, String, Text

from common.mixin import AuditTimeMixin
from config.database import Base


class StockStrategyRun(AuditTimeMixin, Base):
    """Persisted result of an asynchronous strategy backtest."""

    __tablename__ = 'stock_strategy_run'
    __table_args__ = {'comment': '股票策略回测记录表'}

    run_id = Column(String(36), primary_key=True, nullable=False, comment='回测运行ID')
    strategy_name = Column(String(64), nullable=False, index=True, comment='策略模块名')
    code = Column(String(6), nullable=False, comment='股票代码')
    start_date = Column(String(10), nullable=False, comment='开始日期')
    end_date = Column(String(10), nullable=False, comment='结束日期')
    initial_cash = Column(BigInteger, nullable=False, comment='初始资金')
    commission_rate = Column(String(32), nullable=False, comment='手续费率')
    stamp_tax_rate = Column(String(32), nullable=False, default='0.001', comment='卖出印花税率')
    benchmark_code = Column(String(6), nullable=True, comment='基准代码')
    strategy_params = Column(JSON, nullable=False, default=dict, comment='策略参数JSON')
    status = Column(String(16), nullable=False, default='pending', index=True, comment='pending/running/success/failed')
    progress = Column(BigInteger, nullable=False, default=0, comment='进度百分比')
    error_message = Column(Text, nullable=True, comment='错误信息')
    summary = Column(JSON, nullable=True, comment='收益指标JSON')
    curves = Column(JSON, nullable=True, comment='收益曲线JSON')
    trades = Column(JSON, nullable=True, comment='成交明细JSON')
    run_logs = Column(JSON, nullable=True, comment='运行日志JSON')
