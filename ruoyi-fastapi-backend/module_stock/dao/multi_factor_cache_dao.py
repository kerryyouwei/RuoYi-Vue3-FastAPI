from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from module_stock.entity.do.multi_factor_do import (
    MultiFactorFinancialCache,
    MultiFactorIndustryCache,
    MultiFactorKlineCache,
)
from utils.log_util import logger


class MultiFactorCacheDao:
    """多因子本地数据缓存DAO。"""

    # ============ K线缓存 ============

    @staticmethod
    async def get_kline_last_date(db: AsyncSession, code: str) -> date | None:
        """获取某只股票K线缓存中最近的交易日期。"""
        stmt = select(func.max(MultiFactorKlineCache.trade_date)).where(MultiFactorKlineCache.code == code)
        return (await db.execute(stmt)).scalars().first()

    @staticmethod
    async def get_kline_count(db: AsyncSession) -> int:
        stmt = select(func.count(MultiFactorKlineCache.id))
        return (await db.execute(stmt)).scalars().first() or 0

    @staticmethod
    async def load_kline_cache(db: AsyncSession, pure_codes: list[str] | None = None) -> list[MultiFactorKlineCache]:
        """从DB读取K线缓存。"""
        stmt = select(MultiFactorKlineCache)
        if pure_codes:
            stmt = stmt.where(MultiFactorKlineCache.pure_code.in_(pure_codes))
        stmt = stmt.order_by(MultiFactorKlineCache.pure_code, MultiFactorKlineCache.trade_date)
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def upsert_kline(db: AsyncSession, records: list[MultiFactorKlineCache]) -> int:
        """批量写入K线缓存（冲突时更新）。"""
        if not records:
            return 0
        try:
            db.add_all(records)
            await db.flush()
            return len(records)
        except Exception:
            await db.rollback()
            # 逐条写入，跳过冲突
            written = 0
            for rec in records:
                try:
                    db.add(rec)
                    await db.flush()
                    written += 1
                except Exception:
                    await db.rollback()
            return written

    @staticmethod
    async def clear_kline_cache(db: AsyncSession) -> None:
        await db.execute(delete(MultiFactorKlineCache))

    # ============ 财务数据缓存 ============

    @staticmethod
    async def load_financial_cache(db: AsyncSession) -> list[MultiFactorFinancialCache]:
        stmt = select(MultiFactorFinancialCache).order_by(MultiFactorFinancialCache.pure_code)
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def upsert_financial(db: AsyncSession, records: list[MultiFactorFinancialCache]) -> int:
        if not records:
            return 0
        try:
            db.add_all(records)
            await db.flush()
            return len(records)
        except Exception:
            await db.rollback()
            written = 0
            for rec in records:
                try:
                    db.add(rec)
                    await db.flush()
                    written += 1
                except Exception:
                    await db.rollback()
            return written

    # ============ 行业分类缓存 ============

    @staticmethod
    async def load_industry_cache(db: AsyncSession) -> list[MultiFactorIndustryCache]:
        stmt = select(MultiFactorIndustryCache)
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def get_industry_last_update(db: AsyncSession) -> date | None:
        stmt = select(func.max(MultiFactorIndustryCache.update_date))
        return (await db.execute(stmt)).scalars().first()

    @staticmethod
    async def upsert_industry(db: AsyncSession, records: list[MultiFactorIndustryCache]) -> int:
        if not records:
            return 0
        try:
            db.add_all(records)
            await db.flush()
            return len(records)
        except Exception:
            await db.rollback()
            written = 0
            for rec in records:
                try:
                    db.add(rec)
                    await db.flush()
                    written += 1
                except Exception:
                    await db.rollback()
            return written

    @staticmethod
    async def clear_industry_cache(db: AsyncSession) -> None:
        await db.execute(delete(MultiFactorIndustryCache))
