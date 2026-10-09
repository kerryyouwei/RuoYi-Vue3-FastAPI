"""批量回测选股（scan）与模拟交易（paper）子系统数据库实体。"""

from sqlalchemy import JSON, BigInteger, Column, Float, Index, Integer, String, Text, UniqueConstraint

from common.mixin import AuditTimeMixin
from config.database import Base


class StockScanBatch(AuditTimeMixin, Base):
    """批量回测选股批次记录。"""

    __tablename__ = 'stock_scan_batch'
    __table_args__ = (
        Index('ix_stock_scan_batch_status', 'status'),
        {'comment': '批量回测选股批次表'},
    )

    batch_id = Column(String(36), primary_key=True, nullable=False, comment='批次ID')
    strategy_name = Column(String(64), nullable=False, index=True, comment='策略模块名')
    pool_name = Column(String(64), nullable=False, index=True, comment='股票池名称')
    start_date = Column(String(10), nullable=False, comment='开始日期')
    end_date = Column(String(10), nullable=False, comment='结束日期')
    initial_cash = Column(BigInteger, nullable=False, default=1000000, comment='初始资金')
    commission_rate = Column(String(32), nullable=False, default='0.0003', comment='手续费率')
    stamp_tax_rate = Column(String(32), nullable=False, default='0.001', comment='卖出印花税率')
    benchmark_code = Column(String(6), nullable=True, comment='基准代码')
    strategy_params = Column(JSON, nullable=False, default=dict, comment='策略参数JSON')
    status = Column(String(16), nullable=False, default='pending', comment='pending/running/success/failed')
    progress = Column(BigInteger, nullable=False, default=0, comment='进度百分比')
    total_count = Column(BigInteger, nullable=False, default=0, comment='股票总数')
    success_count = Column(BigInteger, nullable=False, default=0, comment='成功数')
    failed_count = Column(BigInteger, nullable=False, default=0, comment='失败数')
    error_message = Column(Text, nullable=True, comment='批次级错误信息')


class StockScanItem(AuditTimeMixin, Base):
    """批量回测选股单只标的回测结果。"""

    __tablename__ = 'stock_scan_item'
    __table_args__ = (
        UniqueConstraint('batch_id', 'code', name='uq_stock_scan_item_batch_code'),
        Index('ix_stock_scan_item_batch_id', 'batch_id'),
        {'comment': '批量回测选股结果表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='记录ID')
    batch_id = Column(String(36), nullable=False, comment='批次ID')
    code = Column(String(6), nullable=False, index=True, comment='6位股票代码')
    name = Column(String(100), nullable=True, comment='股票简称')
    status = Column(String(16), nullable=False, default='pending', comment='pending/running/success/failed')
    summary = Column(JSON, nullable=True, comment='回测指标JSON')
    error_message = Column(Text, nullable=True, comment='错误信息')
    return_rate = Column(Float, nullable=True, comment='策略收益率')
    annual_return = Column(Float, nullable=True, comment='年化收益率')
    sharpe_ratio = Column(Float, nullable=True, comment='夏普比率')
    max_drawdown = Column(Float, nullable=True, comment='最大回撤')
    win_rate = Column(Float, nullable=True, comment='胜率')
    profit_loss_ratio = Column(Float, nullable=True, comment='盈亏比')
    trade_count = Column(Integer, nullable=True, comment='交易次数')


class StockPaperAccount(AuditTimeMixin, Base):
    """模拟盘账户（系统级共享单账户）。"""

    __tablename__ = 'stock_paper_account'
    __table_args__ = (
        UniqueConstraint('account_name', name='uq_stock_paper_account_name'),
        {'comment': '模拟交易账户表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='记录ID')
    account_name = Column(String(64), nullable=False, default='default', comment='账户名称')
    strategy_name = Column(String(64), nullable=True, comment='策略模块名')
    initial_cash = Column(BigInteger, nullable=False, default=1000000, comment='初始资金')
    cash = Column(Float, nullable=False, default=0, comment='可用现金')
    status = Column(String(16), nullable=False, default='active', comment='active/inactive')


class StockPaperUniverse(AuditTimeMixin, Base):
    """模拟盘标的池。"""

    __tablename__ = 'stock_paper_universe'
    __table_args__ = (
        UniqueConstraint('account_id', 'code', name='uq_stock_paper_universe_account_code'),
        {'comment': '模拟盘标的池表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='记录ID')
    account_id = Column(BigInteger, nullable=False, index=True, comment='账户ID')
    code = Column(String(6), nullable=False, index=True, comment='6位股票代码')
    name = Column(String(100), nullable=True, comment='股票简称')
    source_batch_id = Column(String(36), nullable=True, comment='来源回测批次ID')
    status = Column(String(16), nullable=False, default='active', comment='active/inactive')


class StockPaperSignal(AuditTimeMixin, Base):
    """模拟盘每日产出的交易信号。"""

    __tablename__ = 'stock_paper_signal'
    __table_args__ = (
        UniqueConstraint('account_id', 'code', 'signal_date', name='uq_stock_paper_signal_account_code_date'),
        {'comment': '模拟盘交易信号表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='记录ID')
    account_id = Column(BigInteger, nullable=False, index=True, comment='账户ID')
    code = Column(String(6), nullable=False, index=True, comment='6位股票代码')
    signal_date = Column(String(10), nullable=False, comment='信号产生日期')
    signal = Column(String(8), nullable=False, default='持有', comment='买入/卖出/持有')
    reason = Column(String(500), nullable=True, comment='信号原因')
    close_price = Column(Float, nullable=True, comment='产生信号日收盘价')
    execute_date = Column(String(10), nullable=True, index=True, comment='执行日期（次一交易日）')
    status = Column(String(16), nullable=False, default='pending', comment='pending/executed/skipped/expired')


class StockPaperPosition(AuditTimeMixin, Base):
    """模拟盘持仓。"""

    __tablename__ = 'stock_paper_position'
    __table_args__ = (
        UniqueConstraint('account_id', 'code', name='uq_stock_paper_position_account_code'),
        {'comment': '模拟盘持仓表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='记录ID')
    account_id = Column(BigInteger, nullable=False, index=True, comment='账户ID')
    code = Column(String(6), nullable=False, index=True, comment='6位股票代码')
    name = Column(String(100), nullable=True, comment='股票简称')
    quantity = Column(BigInteger, nullable=False, default=0, comment='持仓数量')
    available_quantity = Column(BigInteger, nullable=False, default=0, comment='可卖数量（T+1）')
    avg_cost = Column(Float, nullable=False, default=0, comment='持仓成本')
    last_price = Column(Float, nullable=True, comment='最新价')


class StockPaperOrder(AuditTimeMixin, Base):
    """模拟盘成交/跳过记录。"""

    __tablename__ = 'stock_paper_order'
    __table_args__ = (
        Index('ix_stock_paper_order_account_date', 'account_id', 'execute_date'),
        {'comment': '模拟盘交易记录表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='记录ID')
    account_id = Column(BigInteger, nullable=False, index=True, comment='账户ID')
    code = Column(String(6), nullable=False, index=True, comment='6位股票代码')
    name = Column(String(100), nullable=True, comment='股票简称')
    signal_date = Column(String(10), nullable=True, comment='信号产生日期')
    execute_date = Column(String(10), nullable=False, comment='执行日期')
    side = Column(String(8), nullable=False, comment='买入/卖出')
    price = Column(Float, nullable=True, comment='成交价')
    quantity = Column(BigInteger, nullable=False, default=0, comment='成交数量')
    amount = Column(Float, nullable=False, default=0, comment='成交金额')
    commission = Column(Float, nullable=False, default=0, comment='佣金')
    stamp_tax = Column(Float, nullable=False, default=0, comment='印花税')
    execute_status = Column(String(16), nullable=False, default='成交', comment='成交/跳过')
    skip_reason = Column(String(500), nullable=True, comment='跳过原因')


class StockPaperDailySnapshot(AuditTimeMixin, Base):
    """模拟盘每日净值快照。"""

    __tablename__ = 'stock_paper_daily_snapshot'
    __table_args__ = (
        UniqueConstraint('account_id', 'date', name='uq_stock_paper_snapshot_account_date'),
        {'comment': '模拟盘每日净值快照表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='记录ID')
    account_id = Column(BigInteger, nullable=False, index=True, comment='账户ID')
    date = Column(String(10), nullable=False, comment='快照日期')
    total_equity = Column(Float, nullable=False, default=0, comment='总资产')
    cash = Column(Float, nullable=False, default=0, comment='现金')
    position_value = Column(Float, nullable=False, default=0, comment='持仓市值')
    pnl = Column(Float, nullable=True, comment='累计盈亏')
    return_rate = Column(Float, nullable=True, comment='累计收益率')
