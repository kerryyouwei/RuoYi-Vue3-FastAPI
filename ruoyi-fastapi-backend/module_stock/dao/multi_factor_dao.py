from sqlalchemy import Select, func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from module_admin.entity.do.config_do import SysConfig
from module_stock.entity.do.multi_factor_do import MultiFactorResult, MultiFactorConfig
from module_stock.entity.vo.multi_factor_vo import (
    MultiFactorResultQueryModel,
    MultiFactorWeightSaveItemModel,
)
from utils.page_util import PageUtil


class MultiFactorDao:
    DEFAULT_SELECTED_THRESHOLD = 90.0
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
    async def get_selected_results(
        db: AsyncSession, batch_id: str, codes: list[str] | None = None
    ) -> list[MultiFactorResult]:
        stmt = (
            select(MultiFactorResult)
            .where(MultiFactorResult.batch_id == batch_id, MultiFactorResult.selected == 1)
            .order_by(MultiFactorResult.total_score.desc())
        )
        if codes is not None:
            stmt = stmt.where(MultiFactorResult.code.in_(codes))
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def get_weights(db: AsyncSession) -> list[MultiFactorConfig]:
        stmt = select(MultiFactorConfig).where(MultiFactorConfig.enabled == 1).order_by(MultiFactorConfig.id)
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def get_all_weights(db: AsyncSession) -> list[MultiFactorConfig]:
        stmt = select(MultiFactorConfig).order_by(MultiFactorConfig.id)
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def get_selected_threshold(db: AsyncSession) -> float:
        stmt = select(SysConfig.config_value).where(
            SysConfig.config_key == 'stock.multiFactor.selected_threshold'
        ).limit(1)
        raw_value = (await db.execute(stmt)).scalars().first()
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return MultiFactorDao.DEFAULT_SELECTED_THRESHOLD
        return min(100.0, max(0.0, value))

    @staticmethod
    async def update_selected_threshold(db: AsyncSession, threshold: float) -> None:
        value = f'{round(float(threshold), 2):.2f}'
        stmt = select(SysConfig).where(
            SysConfig.config_key == 'stock.multiFactor.selected_threshold'
        ).limit(1)
        row = (await db.execute(stmt)).scalars().first()
        if row:
            row.config_value = value
        else:
            db.add(SysConfig(
                config_name='多因子入选分数阈值',
                config_key='stock.multiFactor.selected_threshold',
                config_value=value,
                config_type='Y',
                remark='多因子选股入选总分阈值',
            ))

    @staticmethod
    async def update_weights(db: AsyncSession, items: list[MultiFactorWeightSaveItemModel]) -> int:
        """更新已有因子配置；缺失配置时按默认项补建。"""
        rows = await MultiFactorDao.get_all_weights(db)
        row_map = {row.factor_name: row for row in rows}
        changed_count = 0

        for item in items:
            row = row_map.get(item.factor_name)
            weight = round(float(item.weight), 2)
            enabled = 1 if item.enabled else 0
            if row is None:
                db.add(MultiFactorConfig(
                    factor_name=item.factor_name,
                    factor_weight=weight,
                    enabled=enabled,
                ))
            else:
                row.factor_weight = weight
                row.enabled = enabled
            changed_count += 1

        await db.flush()
        return changed_count

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
