"""模拟交易（paper）数据访问层。"""

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from module_stock.entity.do.stock_paper_do import (
    StockPaperAccount,
    StockPaperDailySnapshot,
    StockPaperOrder,
    StockPaperPosition,
    StockPaperSignal,
    StockPaperUniverse,
)
from utils.page_util import PageUtil


class StockPaperDao:
    """模拟盘账户、标的池、持仓、信号、成交与快照的持久化。"""

    # ------------------------------------------------------------------ account
    @staticmethod
    async def get_account(db: AsyncSession, account_name: str) -> StockPaperAccount | None:
        return (
            await db.execute(select(StockPaperAccount).where(StockPaperAccount.account_name == account_name))
        ).scalars().first()

    @staticmethod
    async def create_account(db: AsyncSession, account: StockPaperAccount) -> StockPaperAccount:
        db.add(account)
        await db.flush()
        return account

    @staticmethod
    async def update_account(db: AsyncSession, account_id: int, **values: object) -> None:
        await db.execute(update(StockPaperAccount).where(StockPaperAccount.id == account_id).values(**values))

    # ---------------------------------------------------------------- universe
    @staticmethod
    async def get_universe(db: AsyncSession, account_id: int) -> list[StockPaperUniverse]:
        rows = await db.execute(
            select(StockPaperUniverse).where(StockPaperUniverse.account_id == account_id, StockPaperUniverse.status == 'active').order_by(StockPaperUniverse.code)
        )
        return list(rows.scalars().all())

    @staticmethod
    async def get_universe_by_code(db: AsyncSession, account_id: int, code: str) -> StockPaperUniverse | None:
        return (
            await db.execute(select(StockPaperUniverse).where(StockPaperUniverse.account_id == account_id, StockPaperUniverse.code == code))
        ).scalars().first()

    @staticmethod
    async def add_universe(db: AsyncSession, universe: StockPaperUniverse) -> StockPaperUniverse:
        db.add(universe)
        await db.flush()
        return universe

    @staticmethod
    async def update_universe_by_code(db: AsyncSession, account_id: int, code: str, **values: object) -> None:
        await db.execute(
            update(StockPaperUniverse)
            .where(StockPaperUniverse.account_id == account_id, StockPaperUniverse.code == code)
            .values(**values)
        )

    async def deactivate_universe_except(self: AsyncSession, account_id: int, codes: set[str]) -> None:
        stmt = update(StockPaperUniverse).where(StockPaperUniverse.account_id == account_id).values(status='inactive')
        if codes:
            stmt = stmt.where(StockPaperUniverse.code.not_in(codes))
        await self.execute(stmt)

    async def delete_universe_by_account(self: AsyncSession, account_id: int) -> None:
        await self.execute(delete(StockPaperUniverse).where(StockPaperUniverse.account_id == account_id))

    # ------------------------------------------------------------------ signal
    @staticmethod
    async def get_signal(db: AsyncSession, account_id: int, code: str, signal_date: str) -> StockPaperSignal | None:
        return (
            await db.execute(
                select(StockPaperSignal).where(
                    StockPaperSignal.account_id == account_id,
                    StockPaperSignal.code == code,
                    StockPaperSignal.signal_date == signal_date,
                )
            )
        ).scalars().first()

    @staticmethod
    async def create_signal(db: AsyncSession, signal: StockPaperSignal) -> StockPaperSignal:
        db.add(signal)
        await db.flush()
        return signal

    @staticmethod
    async def update_signal(db: AsyncSession, signal_id: int, **values: object) -> None:
        await db.execute(update(StockPaperSignal).where(StockPaperSignal.id == signal_id).values(**values))

    @staticmethod
    async def list_signals(db: AsyncSession, account_id: int, page_num: int, page_size: int) -> PageModel:
        stmt = select(StockPaperSignal).where(StockPaperSignal.account_id == account_id).order_by(
            StockPaperSignal.signal_date.desc(), StockPaperSignal.code
        )
        return await PageUtil.paginate(db, stmt, page_num, page_size, True)

    @staticmethod
    async def pending_signals_by_execute_date(db: AsyncSession, account_id: int, execute_date: str) -> list[StockPaperSignal]:
        rows = await db.execute(
            select(StockPaperSignal).where(
                StockPaperSignal.account_id == account_id,
                StockPaperSignal.execute_date == execute_date,
                StockPaperSignal.status == 'pending',
            ).order_by(StockPaperSignal.code)
        )
        return list(rows.scalars().all())

    @staticmethod
    async def delete_signals_by_account(db: AsyncSession, account_id: int) -> None:
        await db.execute(delete(StockPaperSignal).where(StockPaperSignal.account_id == account_id))

    # ---------------------------------------------------------------- position
    @staticmethod
    async def get_position(db: AsyncSession, account_id: int, code: str) -> StockPaperPosition | None:
        return (
            await db.execute(select(StockPaperPosition).where(StockPaperPosition.account_id == account_id, StockPaperPosition.code == code))
        ).scalars().first()

    @staticmethod
    async def create_position(db: AsyncSession, position: StockPaperPosition) -> StockPaperPosition:
        db.add(position)
        await db.flush()
        return position

    @staticmethod
    async def update_position(db: AsyncSession, position_id: int, **values: object) -> None:
        await db.execute(update(StockPaperPosition).where(StockPaperPosition.id == position_id).values(**values))

    @staticmethod
    async def list_positions(db: AsyncSession, account_id: int) -> list[StockPaperPosition]:
        rows = await db.execute(
            select(StockPaperPosition).where(StockPaperPosition.account_id == account_id).order_by(StockPaperPosition.code)
        )
        return list(rows.scalars().all())

    @staticmethod
    async def settle_positions(db: AsyncSession, account_id: int) -> None:
        """T+1 结算：将可卖数量置为全部持仓。"""
        await db.execute(
            update(StockPaperPosition).where(StockPaperPosition.account_id == account_id).values(available_quantity=StockPaperPosition.quantity)
        )

    @staticmethod
    async def delete_position(db: AsyncSession, position: StockPaperPosition) -> None:
        await db.delete(position)
        await db.flush()

    @staticmethod
    async def delete_positions_by_code(db: AsyncSession, account_id: int, code: str) -> None:
        await db.execute(delete(StockPaperPosition).where(StockPaperPosition.account_id == account_id, StockPaperPosition.code == code))

    async def delete_positions_by_account(self: AsyncSession, account_id: int) -> None:
        await self.execute(delete(StockPaperPosition).where(StockPaperPosition.account_id == account_id))

    # ------------------------------------------------------------------ order
    @staticmethod
    async def create_order(db: AsyncSession, order: StockPaperOrder) -> StockPaperOrder:
        db.add(order)
        await db.flush()
        return order

    @staticmethod
    async def list_orders(db: AsyncSession, account_id: int, page_num: int, page_size: int) -> PageModel:
        stmt = select(StockPaperOrder).where(StockPaperOrder.account_id == account_id).order_by(
            StockPaperOrder.execute_date.desc(), StockPaperOrder.id.desc()
        )
        return await PageUtil.paginate(db, stmt, page_num, page_size, True)

    @staticmethod
    async def delete_orders_by_account(db: AsyncSession, account_id: int) -> None:
        await db.execute(delete(StockPaperOrder).where(StockPaperOrder.account_id == account_id))

    # ---------------------------------------------------------------- snapshot
    @staticmethod
    async def get_snapshot(db: AsyncSession, account_id: int, date: str) -> StockPaperDailySnapshot | None:
        return (
            await db.execute(select(StockPaperDailySnapshot).where(StockPaperDailySnapshot.account_id == account_id, StockPaperDailySnapshot.date == date))
        ).scalars().first()

    @staticmethod
    async def create_snapshot(db: AsyncSession, snapshot: StockPaperDailySnapshot) -> StockPaperDailySnapshot:
        db.add(snapshot)
        await db.flush()
        return snapshot

    @staticmethod
    async def update_snapshot(db: AsyncSession, snapshot_id: int, **values: object) -> None:
        await db.execute(update(StockPaperDailySnapshot).where(StockPaperDailySnapshot.id == snapshot_id).values(**values))

    @staticmethod
    async def list_snapshots(db: AsyncSession, account_id: int, start_date: str | None = None, end_date: str | None = None) -> list[StockPaperDailySnapshot]:
        stmt = select(StockPaperDailySnapshot).where(StockPaperDailySnapshot.account_id == account_id)
        if start_date:
            stmt = stmt.where(StockPaperDailySnapshot.date >= start_date)
        if end_date:
            stmt = stmt.where(StockPaperDailySnapshot.date <= end_date)
        stmt = stmt.order_by(StockPaperDailySnapshot.date.asc())
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def delete_snapshots_by_account(db: AsyncSession, account_id: int) -> None:
        await db.execute(delete(StockPaperDailySnapshot).where(StockPaperDailySnapshot.account_id == account_id))
