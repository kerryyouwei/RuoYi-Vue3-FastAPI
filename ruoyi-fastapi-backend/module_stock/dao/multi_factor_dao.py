from sqlalchemy import Select, func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from module_stock.entity.do.multi_factor_do import MultiFactorResult, MultiFactorConfig
from module_stock.entity.vo.multi_factor_vo import MultiFactorResultQueryModel
from utils.page_util import PageUtil


class MultiFactorDao:
    @staticmethod
    async def bulk_create(db: AsyncSession, results: list[MultiFactorResult]) -> None:
        db.add_all(results)
        await db.flush()

    @staticmethod
    async def get_latest_batch_id(db: AsyncSession) -> str | None:
        stmt = select(MultiFactorResult.batch_id).order_by(MultiFactorResult.create_time.desc()).limit(1)
        row = (await db.execute(stmt)).scalars().first()
        return row

    @staticmethod
    async def list_page(db: AsyncSession, query: MultiFactorResultQueryModel, batch_id: str) -> PageModel:
        stmt = select(MultiFactorResult).where(MultiFactorResult.batch_id == batch_id)
        stmt = MultiFactorDao._filter(stmt, query)
        stmt = stmt.order_by(MultiFactorResult.total_score.desc(), MultiFactorResult.code)
        return await PageUtil.paginate(db, stmt, query.page_num, query.page_size, True)

    @staticmethod
    async def count_batch(db: AsyncSession, batch_id: str, selected_only: bool = False) -> int:
        stmt = select(func.count(MultiFactorResult.id)).where(MultiFactorResult.batch_id == batch_id)
        if selected_only:
            stmt = stmt.where(MultiFactorResult.selected == 1)
        row = (await db.execute(stmt)).scalars().first()
        return row or 0

    @staticmethod
    async def get_batch_info(db: AsyncSession, batch_id: str) -> dict:
        total = await MultiFactorDao.count_batch(db, batch_id)
        selected = await MultiFactorDao.count_batch(db, batch_id, selected_only=True)
        # 获取降级因子
        stmt = select(MultiFactorResult.factor_degraded).where(
            MultiFactorResult.batch_id == batch_id,
            MultiFactorResult.factor_degraded.isnot(None),
        ).limit(1)
        degraded_str = (await db.execute(stmt)).scalars().first()
        degraded = degraded_str.split(',') if degraded_str else []
        # 获取计算日期
        stmt2 = select(MultiFactorResult.calc_date).where(MultiFactorResult.batch_id == batch_id).limit(1)
        calc_date = (await db.execute(stmt2)).scalars().first()
        return {
            'batch_id': batch_id,
            'total_count': total,
            'selected_count': selected,
            'degraded_factors': degraded,
            'calc_date': calc_date,
        }

    @staticmethod
    async def get_selected_results(db: AsyncSession, batch_id: str) -> list[MultiFactorResult]:
        stmt = (
            select(MultiFactorResult)
            .where(MultiFactorResult.batch_id == batch_id, MultiFactorResult.selected == 1)
            .order_by(MultiFactorResult.total_score.desc())
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def get_weights(db: AsyncSession) -> list[MultiFactorConfig]:
        stmt = select(MultiFactorConfig).where(MultiFactorConfig.enabled == 1).order_by(MultiFactorConfig.id)
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def delete_batch(db: AsyncSession, batch_id: str) -> None:
        await db.execute(delete(MultiFactorResult).where(MultiFactorResult.batch_id == batch_id))

    @staticmethod
    def _filter(stmt: Select, query: MultiFactorResultQueryModel) -> Select:
        if query.selected_only:
            stmt = stmt.where(MultiFactorResult.selected == 1)
        if query.keyword:
            keyword = f'%{query.keyword}%'
            stmt = stmt.where(MultiFactorResult.code.like(keyword) | MultiFactorResult.name.like(keyword))
        return stmt
