from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_stock.entity.do.stock_strategy_do import StockStrategyRun, StockStrategyValidation
from module_stock.entity.vo.stock_strategy_vo import StrategyValidationQueryModel
from utils.page_util import PageModel, PageUtil


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

    # 历史列表/策略列表只用轻量列；curves/trades/run_logs 是大 JSON，
    # 全量选取会让 MySQL ORDER BY 超出 sort buffer（error 1038）。
    _RUN_LIGHT_COLUMNS = (
        StockStrategyRun.run_id,
        StockStrategyRun.strategy_name,
        StockStrategyRun.code,
        StockStrategyRun.pool_name,
        StockStrategyRun.start_date,
        StockStrategyRun.end_date,
        StockStrategyRun.status,
        StockStrategyRun.progress,
        StockStrategyRun.create_time,
        StockStrategyRun.summary,
    )

    @staticmethod
    async def list_for_strategy(db: AsyncSession, strategy_name: str, page_num: int, page_size: int) -> PageModel:
        query = (
            select(*StockStrategyDao._RUN_LIGHT_COLUMNS)
            .where(StockStrategyRun.strategy_name == strategy_name)
            .order_by(StockStrategyRun.create_time.desc())
        )
        return await PageUtil.paginate(db, query, page_num, page_size, True)

    @staticmethod
    async def summaries(db: AsyncSession) -> dict[str, dict]:
        rows = (
            await db.execute(
                select(
                    StockStrategyRun.strategy_name,
                    StockStrategyRun.create_time,
                    StockStrategyRun.status,
                    StockStrategyRun.summary,
                ).order_by(StockStrategyRun.create_time.desc())
            )
        ).all()
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

    # ---------------------------------------------------------------- validation

    @staticmethod
    async def create_validation(db: AsyncSession, validation: StockStrategyValidation) -> StockStrategyValidation:
        db.add(validation)
        await db.flush()
        return validation

    @staticmethod
    async def get_validation(db: AsyncSession, validation_id: str) -> StockStrategyValidation | None:
        stmt = select(StockStrategyValidation).where(StockStrategyValidation.validation_id == validation_id)
        return (await db.execute(stmt)).scalars().first()

    @staticmethod
    async def update_validation(db: AsyncSession, validation_id: str, **values: object) -> None:
        stmt = update(StockStrategyValidation).where(StockStrategyValidation.validation_id == validation_id).values(**values)
        await db.execute(stmt)

    @staticmethod
    async def list_validations(db: AsyncSession, query: StrategyValidationQueryModel) -> PageModel:
        stmt = select(StockStrategyValidation)
        if query.strategy_name:
            stmt = stmt.where(StockStrategyValidation.strategy_name == query.strategy_name)
        stmt = stmt.order_by(StockStrategyValidation.create_time.desc(), StockStrategyValidation.validation_id.desc())
        return await PageUtil.paginate(db, stmt, query.page_num, query.page_size, True)

    @staticmethod
    async def fail_orphaned_validations(db: AsyncSession) -> None:
        stmt = (
            update(StockStrategyValidation)
            .where(StockStrategyValidation.status.in_(('pending', 'running')))
            .values(status='failed', error_message='服务重启导致滚动验证中断', progress=100)
        )
        await db.execute(stmt)
