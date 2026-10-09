"""批量回测选股（scan）数据访问层。"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from module_stock.entity.do.stock_paper_do import StockScanBatch, StockScanItem
from module_stock.entity.vo.stock_paper_vo import ScanItemQueryModel
from utils.page_util import PageUtil

_SCAN_SORT_COLUMNS = {
    'return_rate': StockScanItem.return_rate,
    'sharpe_ratio': StockScanItem.sharpe_ratio,
    'max_drawdown': StockScanItem.max_drawdown,
    'win_rate': StockScanItem.win_rate,
    'trade_count': StockScanItem.trade_count,
}


class StockScanDao:
    """批量回测选股批次的增删改查。"""

    @staticmethod
    async def create_batch(db: AsyncSession, batch: StockScanBatch) -> StockScanBatch:
        db.add(batch)
        await db.flush()
        return batch

    @staticmethod
    async def get_batch(db: AsyncSession, batch_id: str) -> StockScanBatch | None:
        return (await db.execute(select(StockScanBatch).where(StockScanBatch.batch_id == batch_id))).scalars().first()

    @staticmethod
    async def update_batch(db: AsyncSession, batch_id: str, **values: object) -> None:
        await db.execute(update(StockScanBatch).where(StockScanBatch.batch_id == batch_id).values(**values))

    @staticmethod
    async def bulk_create_items(db: AsyncSession, items: list[StockScanItem]) -> None:
        db.add_all(items)
        await db.flush()

    @staticmethod
    async def get_item(db: AsyncSession, item_id: int) -> StockScanItem | None:
        return (await db.execute(select(StockScanItem).where(StockScanItem.id == item_id))).scalars().first()

    @staticmethod
    async def update_item(db: AsyncSession, item_id: int, **values: object) -> None:
        await db.execute(update(StockScanItem).where(StockScanItem.id == item_id).values(**values))

    @staticmethod
    async def get_items_by_batch(db: AsyncSession, batch_id: str) -> list[StockScanItem]:
        rows = await db.execute(select(StockScanItem).where(StockScanItem.batch_id == batch_id).order_by(StockScanItem.code))
        return list(rows.scalars().all())

    @staticmethod
    async def get_items_for_codes(db: AsyncSession, batch_id: str, codes: list[str]) -> list[StockScanItem]:
        if not codes:
            return []
        rows = await db.execute(
            select(StockScanItem).where(StockScanItem.batch_id == batch_id, StockScanItem.code.in_(codes))
        )
        return list(rows.scalars().all())

    @staticmethod
    async def count_items_by_status(db: AsyncSession, batch_id: str) -> dict[str, int]:
        rows = await db.execute(
            select(StockScanItem.status, func.count(StockScanItem.id))
            .where(StockScanItem.batch_id == batch_id)
            .group_by(StockScanItem.status)
        )
        return {status: int(count) for status, count in rows}

    @staticmethod
    async def list_items(db: AsyncSession, batch_id: str, query: ScanItemQueryModel) -> PageModel:
        stmt = select(StockScanItem).where(StockScanItem.batch_id == batch_id)
        if query.status:
            stmt = stmt.where(StockScanItem.status == query.status)
        column = _SCAN_SORT_COLUMNS.get(query.sort_by, StockScanItem.return_rate)
        ordering = column.asc() if query.order == 'asc' else column.desc()
        # NULL 指标统一排在最后，保证成功记录优先展示。
        stmt = stmt.order_by(column.is_(None), ordering, StockScanItem.id.desc())
        return await PageUtil.paginate(db, stmt, query.page_num, query.page_size, True)
