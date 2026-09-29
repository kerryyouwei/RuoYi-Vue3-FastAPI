from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from module_stock.entity.do.stock_selector_do import StockPoolItem
from module_stock.entity.vo.stock_selector_vo import StockPoolNameModel, StockPoolQueryModel
from utils.page_util import PageUtil


class StockPoolDao:
    @staticmethod
    async def create(db: AsyncSession, item: StockPoolItem) -> StockPoolItem:
        db.add(item)
        await db.flush()
        return item

    @staticmethod
    async def get(db: AsyncSession, item_id: int) -> StockPoolItem | None:
        return (await db.execute(select(StockPoolItem).where(StockPoolItem.id == item_id))).scalars().first()

    @staticmethod
    async def get_existing_codes(db: AsyncSession, pool_name: str, codes: list[str]) -> set[str]:
        if not codes:
            return set()
        rows = await db.execute(
            select(StockPoolItem.code).where(StockPoolItem.pool_name == pool_name, StockPoolItem.code.in_(codes))
        )
        return set(rows.scalars().all())

    @staticmethod
    async def list_page(db: AsyncSession, query: StockPoolQueryModel) -> PageModel:
        stmt = select(StockPoolItem).order_by(StockPoolItem.create_time.desc(), StockPoolItem.id.desc())
        stmt = StockPoolDao._filter(stmt, query)
        return await PageUtil.paginate(db, stmt, query.page_num, query.page_size, True)

    @staticmethod
    async def pool_names(db: AsyncSession) -> list[StockPoolNameModel]:
        rows = await db.execute(
            select(StockPoolItem.pool_name, func.count(StockPoolItem.id))
            .group_by(StockPoolItem.pool_name)
            .order_by(StockPoolItem.pool_name)
        )
        return [StockPoolNameModel(pool_name=row[0], stock_count=row[1]) for row in rows]

    @staticmethod
    async def delete(db: AsyncSession, item: StockPoolItem) -> None:
        await db.delete(item)
        await db.flush()

    @staticmethod
    def _filter(stmt: Select, query: StockPoolQueryModel) -> Select:
        if query.pool_name:
            stmt = stmt.where(StockPoolItem.pool_name == query.pool_name)
        if query.keyword:
            keyword = f'%{query.keyword}%'
            stmt = stmt.where(StockPoolItem.code.like(keyword) | StockPoolItem.name.like(keyword))
        return stmt

