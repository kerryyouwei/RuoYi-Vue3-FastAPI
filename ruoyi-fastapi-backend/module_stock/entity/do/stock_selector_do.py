from sqlalchemy import BigInteger, Column, String, Text, UniqueConstraint

from common.mixin import AuditTimeMixin
from config.database import Base


class StockPoolItem(AuditTimeMixin, Base):
    """股票池明细，用于保存手动选股结果并供后续回测读取。"""

    __tablename__ = 'stock_pool_item'
    __table_args__ = (
        UniqueConstraint('pool_name', 'code', name='uq_stock_pool_item_pool_code'),
        {'comment': '股票池明细表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='记录ID')
    pool_name = Column(String(64), nullable=False, default='default', index=True, comment='股票池名称')
    code = Column(String(6), nullable=False, index=True, comment='6位股票代码')
    name = Column(String(100), nullable=True, comment='股票简称')
    source_query = Column(Text, nullable=True, comment='加入时的问财查询条件')
    source = Column(String(32), nullable=False, default='iwencai', comment='数据来源')
    remark = Column(String(255), nullable=True, comment='备注')
