from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_stock.entity.do.stock_strategy_do import StockStrategyRun
from utils.page_util import PageUtil


class StockStrategyDao:
    @staticmethod
    async def create(db: AsyncSession, run: StockStrategyRun) -> StockStrategyRun:
        db.add(run)
        await db.flush()
        return run

    @staticmethod
    async def get(db: AsyncSession, run_id: str) -> StockStrategyRun | None:
        return (await db.execute(select(StockStrategyRun).where(StockStrategyRun.run_id == run_id))).scalars().first()

    @staticmethod
    async def update(db: AsyncSession, run_id: str, **values: object) -> None:
        await db.execute(update(StockStrategyRun).where(StockStrategyRun.run_id == run_id).values(**values))

    @staticmethod
    async def list_for_strategy(db: AsyncSession, strategy_name: str, page_num: int, page_size: int):
        query = select(StockStrategyRun).where(StockStrategyRun.strategy_name == strategy_name).order_by(StockStrategyRun.create_time.desc())
        return await PageUtil.paginate(db, query, page_num, page_size, True)

    @staticmethod
    async def summaries(db: AsyncSession) -> dict[str, dict]:
        rows = (await db.execute(select(StockStrategyRun).order_by(StockStrategyRun.create_time.desc()))).scalars().all()
        result: dict[str, dict] = {}
        for row in rows:
            item = result.setdefault(row.strategy_name, {'run_count': 0, 'last': row})
            item['run_count'] += 1
        return result

    @staticmethod
    async def fail_orphaned(db: AsyncSession) -> None:
        await db.execute(
            update(StockStrategyRun).where(StockStrategyRun.status.in_(('pending', 'running'))).values(
                status='failed', error_message='服务重启导致回测中断', progress=100
            )
        )
