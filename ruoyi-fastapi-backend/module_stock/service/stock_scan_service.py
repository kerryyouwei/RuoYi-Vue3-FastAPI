"""股票池批量回测选股服务。"""

import asyncio
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.database import DataSourceRegistry
from exceptions.exception import ServiceException
from module_stock.dao.stock_pool_dao import StockPoolDao
from module_stock.dao.stock_scan_dao import StockScanDao
from module_stock.entity.do.stock_paper_do import StockScanBatch, StockScanItem
from module_stock.entity.vo.stock_paper_vo import ScanBatchModel, ScanItemQueryModel, ScanRunRequestModel
from module_stock.service.stock_strategy_service import StockStrategyService
from utils.log_util import logger

_RUNNING_TASKS: set[asyncio.Task[None]] = set()


def _log_task_result(task: asyncio.Task[None]) -> None:
    _RUNNING_TASKS.discard(task)
    if task.cancelled():
        logger.bind(task_name=task.get_name()).warning('批量回测选股任务已取消')
        return
    if exc := task.exception():
        logger.bind(task_name=task.get_name()).error(f'批量回测选股任务未捕获异常：{type(exc).__name__}: {exc}')


class StockScanService:
    """创建并后台执行批量回测批次。"""

    _metric_keys = ('returnRate', 'annualReturn', 'sharpeRatio', 'maxDrawdown', 'winRate', 'profitLossRatio', 'tradeCount')

    @classmethod
    async def run_scan(cls, db: AsyncSession, request: ScanRunRequestModel) -> str:
        StockStrategyService._file(request.strategy_name)
        codes = await StockPoolDao.codes_by_pool(db, request.pool_name)
        if not codes:
            raise ServiceException(message=f'股票池「{request.pool_name}」不存在或为空')
        strategy_params = await asyncio.to_thread(
            StockStrategyService._coerce_strategy_params, request.strategy_name, request.strategy_params
        )

        batch_id = str(uuid.uuid4())
        await StockScanDao.create_batch(
            db,
            StockScanBatch(
                batch_id=batch_id,
                strategy_name=request.strategy_name,
                pool_name=request.pool_name,
                start_date=request.start.isoformat(),
                end_date=request.end.isoformat(),
                initial_cash=request.initial_cash,
                commission_rate=str(request.commission_rate),
                stamp_tax_rate=str(request.stamp_tax_rate),
                benchmark_code=request.benchmark_code,
                strategy_params=strategy_params,
                status='pending',
                progress=0,
                total_count=len(codes),
            ),
        )
        await StockScanDao.bulk_create_items(
            db,
            [
                StockScanItem(batch_id=batch_id, code=code, name=name, status='pending')
                for code, name in codes
            ],
        )
        await db.commit()

        task = asyncio.create_task(cls._execute_scan(batch_id), name=f'stock-scan-{batch_id}')
        _RUNNING_TASKS.add(task)
        task.add_done_callback(_log_task_result)
        logger.bind(batch_id=batch_id, pool_name=request.pool_name, total_count=len(codes)).info('批量回测选股已提交')
        return batch_id

    @classmethod
    async def get_batch(cls, db: AsyncSession, batch_id: str) -> ScanBatchModel:
        batch = await StockScanDao.get_batch(db, batch_id)
        if batch is None:
            raise ServiceException(message='批量回测批次不存在')
        return ScanBatchModel.model_validate(batch)

    @classmethod
    async def list_items(cls, db: AsyncSession, batch_id: str, query: ScanItemQueryModel) -> Any:
        await cls.get_batch(db, batch_id)
        return await StockScanDao.list_items(db, batch_id, query)

    @classmethod
    async def _mark_batch_running(cls, batch_id: str) -> None:
        async with DataSourceRegistry.session(log_sql=False) as db:
            await StockScanDao.update_batch(db, batch_id, status='running', progress=0, error_message=None)
            await db.commit()

    @classmethod
    async def _execute_scan(cls, batch_id: str) -> None:
        async with DataSourceRegistry.session(log_sql=False) as db:
            batch = await StockScanDao.get_batch(db, batch_id)
            items = await StockScanDao.get_items_by_batch(db, batch_id)
        if batch is None or not items:
            logger.bind(batch_id=batch_id).warning('批量回测批次或标的为空，任务终止')
            return
        await cls._mark_batch_running(batch_id)

        context = {
            'strategy_name': batch.strategy_name,
            'start_date': batch.start_date,
            'end_date': batch.end_date,
            'initial_cash': batch.initial_cash,
            'commission_rate': float(batch.commission_rate),
            'stamp_tax_rate': float(batch.stamp_tax_rate),
            'benchmark_code': batch.benchmark_code,
            'strategy_params': batch.strategy_params or {},
        }
        semaphore = asyncio.Semaphore(2)
        total = len(items)
        done: dict[str, int] = {'count': 0}

        async def run_one(item: StockScanItem) -> None:
            try:
                async with semaphore:
                    async with DataSourceRegistry.session(log_sql=False) as db:
                        await StockScanDao.update_item(db, item.id, status='running', error_message=None)
                        await db.commit()
                    try:
                        result = await asyncio.to_thread(StockStrategyService.backtest_once, code=item.code, **context)
                        summary = result.get('summary') or {}
                        async with DataSourceRegistry.session(log_sql=False) as db:
                            await StockScanDao.update_item(
                                db,
                                item.id,
                                status='success',
                                summary=summary,
                                error_message=None,
                                return_rate=StockStrategyService._finite(summary.get('returnRate')),
                                annual_return=StockStrategyService._finite(summary.get('annualReturn')),
                                sharpe_ratio=StockStrategyService._finite(summary.get('sharpeRatio')),
                                max_drawdown=StockStrategyService._finite(summary.get('maxDrawdown')),
                                win_rate=StockStrategyService._finite(summary.get('winRate')),
                                profit_loss_ratio=StockStrategyService._finite(summary.get('profitLossRatio')),
                                trade_count=summary.get('tradeCount'),
                            )
                            await db.commit()
                    except Exception as exc:
                        error_message = f'{type(exc).__name__}: {exc}'[:4000]
                        logger.bind(batch_id=batch_id, code=item.code).exception(f'单只标的回测失败：{error_message}')
                        async with DataSourceRegistry.session(log_sql=False) as db:
                            await StockScanDao.update_item(db, item.id, status='failed', error_message=error_message)
                            await db.commit()
            finally:
                done['count'] += 1
                progress = round(done['count'] / total * 100)
                try:
                    async with DataSourceRegistry.session(log_sql=False) as db:
                        await StockScanDao.update_batch(db, batch_id, progress=progress)
                        await db.commit()
                except Exception:
                    logger.bind(batch_id=batch_id).exception('批量回测进度写入失败')

        await asyncio.gather(*(run_one(item) for item in items), return_exceptions=True)

        async with DataSourceRegistry.session(log_sql=False) as db:
            counts = await StockScanDao.count_items_by_status(db, batch_id)
            success_count = counts.get('success', 0)
            failed_count = counts.get('failed', 0)
            await StockScanDao.update_batch(
                db,
                batch_id,
                status='success',
                progress=100,
                success_count=success_count,
                failed_count=failed_count,
            )
            await db.commit()
        logger.bind(batch_id=batch_id, success_count=success_count, failed_count=failed_count).info('批量回测选股批次执行完成')
