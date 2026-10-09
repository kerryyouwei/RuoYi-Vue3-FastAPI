from typing import Annotated

from fastapi import Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.aspect.db_session import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel
from module_stock.entity.vo.stock_paper_vo import (
    ScanBatchModel,
    ScanItemModel,
    ScanItemQueryModel,
    ScanPickRequestModel,
    ScanRunRequestModel,
)
from module_stock.service.stock_paper_service import StockPaperService
from module_stock.service.stock_scan_service import StockScanService
from utils.log_util import logger
from utils.response_util import ResponseUtil

stock_scan_controller = APIRouterPro(
    prefix='/stock/scan', order_num=20, tags=['股票管理-批量选股回测'], dependencies=[PreAuthDependency()]
)


@stock_scan_controller.post(
    '/run',
    summary='提交股票池批量回测',
    description='选择策略、股票池与回测日期后，后台对池内每只股票逐个回测并落库',
    response_model=DataResponseModel[dict],
    dependencies=[UserInterfaceAuthDependency('stock:scan:run')],
)
async def run_scan(
    request: Request,
    body: ScanRunRequestModel,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    batch_id = await StockScanService.run_scan(db, body)
    logger.bind(batch_id=batch_id, pool_name=body.pool_name, strategy_name=body.strategy_name).info('批量回测已提交')
    return ResponseUtil.success(data={'batchId': batch_id}, msg='批量回测已提交')


@stock_scan_controller.get(
    '/{batch_id}',
    summary='查询批量回测批次状态',
    description='查询某个批量回测批次的整体状态与进度',
    response_model=DataResponseModel[ScanBatchModel],
    dependencies=[UserInterfaceAuthDependency('stock:scan:list')],
)
async def get_scan_batch(
    request: Request,
    batch_id: Annotated[str, Path(max_length=36)],
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    return ResponseUtil.success(data=await StockScanService.get_batch(db, batch_id))


@stock_scan_controller.get(
    '/{batch_id}/items',
    summary='分页查询批量回测结果',
    description='按指标列排序、状态过滤，分页浏览批量回测单只标的结果',
    response_model=PageResponseModel[ScanItemModel],
    dependencies=[UserInterfaceAuthDependency('stock:scan:list')],
)
async def get_scan_items(
    request: Request,
    batch_id: Annotated[str, Path(max_length=36)],
    query: Annotated[ScanItemQueryModel, Query()],
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    return ResponseUtil.success(model_content=await StockScanService.list_items(db, batch_id, query))


@stock_scan_controller.post(
    '/pick',
    summary='勾选写入模拟盘标的池',
    description='将批量回测结果中勾选的股票写入模拟盘标的池（universe）',
    response_model=DataResponseModel[dict],
    dependencies=[UserInterfaceAuthDependency('stock:scan:pick')],
)
async def pick_to_paper(
    request: Request,
    body: ScanPickRequestModel,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await StockPaperService.pick_to_universe(db, body.batch_id, body.codes)
    logger.bind(
        batch_id=body.batch_id, added_count=result['addedCount'], skipped_count=result['skippedCount']
    ).info('回测结果已勾选写入模拟盘标的池')
    return ResponseUtil.success(data=result, msg='已加入模拟盘标的池')
