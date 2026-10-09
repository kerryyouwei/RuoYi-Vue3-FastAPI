from sqlalchemy import BigInteger, Column, Date, Numeric, SmallInteger, String, UniqueConstraint

from common.mixin import AuditTimeMixin
from config.database import Base


class MultiFactorResult(AuditTimeMixin, Base):
    """多因子选股计算结果。"""

    __tablename__ = 'multi_factor_result'
    __table_args__ = (
        UniqueConstraint('batch_id', 'code', name='uq_multi_factor_batch_code'),
        {'comment': '多因子选股结果表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='记录ID')
    batch_id = Column(String(32), nullable=False, index=True, comment='计算批次ID')
    code = Column(String(6), nullable=False, index=True, comment='6位股票代码')
    name = Column(String(100), nullable=True, comment='股票简称')
    total_score = Column(Numeric(6, 2), nullable=False, comment='总分')
    roe_score = Column(Numeric(6, 2), nullable=True, comment='ROE得分')
    peg_score = Column(Numeric(6, 2), nullable=True, comment='PEG得分')
    profit_growth_score = Column(Numeric(6, 2), nullable=True, comment='利润增长得分')
    volume_score = Column(Numeric(6, 2), nullable=True, comment='成交量得分')
    macd_score = Column(Numeric(6, 2), nullable=True, comment='MACD得分')
    northbound_score = Column(Numeric(6, 2), nullable=True, comment='北向持仓变化得分')
    industry_score = Column(Numeric(6, 2), nullable=True, comment='行业景气得分')
    roe_value = Column(Numeric(10, 4), nullable=True, comment='ROE值')
    peg_value = Column(Numeric(10, 4), nullable=True, comment='PEG值')
    profit_growth_value = Column(Numeric(10, 4), nullable=True, comment='利润增长值')
    turnover_rate_value = Column(Numeric(10, 4), nullable=True, comment='换手率值')
    macd_signal = Column(String(20), nullable=True, comment='MACD信号')
    northbound_net = Column(Numeric(16, 2), nullable=True, comment='北向持仓变化值(万元)')
    industry_name = Column(String(50), nullable=True, comment='所属行业')
    industry_growth = Column(Numeric(10, 4), nullable=True, comment='行业营收增速')
    selected = Column(SmallInteger, nullable=False, default=0, comment='是否入选(>=90分)')
    factor_degraded = Column(String(255), nullable=True, comment='降级因子说明')
    calc_date = Column(Date, nullable=False, comment='计算日期')


class MultiFactorConfig(AuditTimeMixin, Base):
    """多因子权重配置。"""

    __tablename__ = 'multi_factor_config'
    __table_args__ = (
        {'comment': '多因子权重配置表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='记录ID')
    factor_name = Column(String(32), nullable=False, unique=True, comment='因子名称')
    factor_weight = Column(Numeric(5, 2), nullable=False, comment='权重百分比')
    enabled = Column(SmallInteger, nullable=False, default=1, comment='是否启用')



class MultiFactorKlineCache(Base):
    """K线数据本地缓存。"""

    __tablename__ = 'multi_factor_kline_cache'
    __table_args__ = (
        UniqueConstraint('code', 'trade_date', name='uq_mf_kline'),
        {'comment': '多因子K线缓存表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(12), nullable=False, comment='Baostock代码')
    pure_code = Column(String(6), nullable=False, index=True, comment='6位代码')
    trade_date = Column(Date, nullable=False, comment='交易日期')
    close = Column(Numeric(12, 4), nullable=True)
    pe_ttm = Column(Numeric(12, 4), nullable=True)
    pb_mrq = Column(Numeric(12, 4), nullable=True)
    turn = Column(Numeric(12, 4), nullable=True)
    volume = Column(Numeric(20, 2), nullable=True)
    amount = Column(Numeric(20, 2), nullable=True)


class MultiFactorFinancialCache(Base):
    """财务数据本地缓存。"""

    __tablename__ = 'multi_factor_financial_cache'
    __table_args__ = (
        UniqueConstraint('code', 'year', 'quarter', name='uq_mf_fin'),
        {'comment': '多因子财务数据缓存表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(12), nullable=False, comment='Baostock代码')
    pure_code = Column(String(6), nullable=False, index=True, comment='6位代码')
    year = Column(BigInteger, nullable=False, comment='年份')
    quarter = Column(BigInteger, nullable=False, comment='季度')
    roe_avg = Column(Numeric(12, 4), nullable=True)
    np_margin = Column(Numeric(12, 4), nullable=True)
    yoy_ni = Column(Numeric(12, 4), nullable=True)
    yoy_equity = Column(Numeric(12, 4), nullable=True)
    stat_date = Column(Date, nullable=True)
    pub_date = Column(Date, nullable=True)


class MultiFactorIndustryCache(Base):
    """行业分类本地缓存。"""

    __tablename__ = 'multi_factor_industry_cache'
    __table_args__ = (
        {'comment': '多因子行业分类缓存表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    pure_code = Column(String(6), nullable=False, unique=True, comment='6位代码')
    code = Column(String(12), nullable=False, comment='Baostock代码')
    industry_name = Column(String(50), nullable=False)
    industry_type = Column(String(20), nullable=True)
    update_date = Column(Date, nullable=False)
