from typing import Annotated

from fastapi import Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.aspect.db_session import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel, ResponseBaseModel
from module_stock.entity.vo.multi_factor_vo import (
    MultiFactorBatchInfoModel,
    MultiFactorCalcResultModel,
    MultiFactorPoolAddRequestModel,
    MultiFactorPoolAddResultModel,
    MultiFactorResultQueryModel,
    MultiFactorResultModel,
)
from module_stock.service.multi_factor_service import MultiFactorService
from utils.log_util import logger
from utils.response_util import ResponseUtil

multi_factor_controller = APIRouterPro(
    prefix='/stock/multi-factor', order_num=18, tags=['股票管理-多因子选股'], dependencies=[PreAuthDependency()]
)


@multi_factor_controller.post(
    '/calculate',
    summary='触发多因子计算',
    description='拉取Baostock全市场数据，计算7因子加权得分，返回计算摘要',
    response_model=DataResponseModel[MultiFactorCalcResultModel],
    dependencies=[UserInterfaceAuthDependency('stock:multiFactor:calculate')],
)
async def calculate_multi_factor(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await MultiFactorService.calculate(db)
    logger.info(
        f'多因子计算完成: batch={result.batch_id} 总数={result.total_count} '
        f'入选={result.selected_count} 耗时={result.elapsed_seconds}s'
    )
    return ResponseUtil.success(data=result, msg='计算完成')


@multi_factor_controller.get(
    '/list',
    summary='查询多因子选股结果',
    description='分页查询计算结果，支持筛选入选/全部',
    response_model=PageResponseModel[MultiFactorResultModel],
    dependencies=[UserInterfaceAuthDependency('stock:multiFactor:list')],
)
async def list_multi_factor_results(
    request: Request,
    query: Annotated[MultiFactorResultQueryModel, Query()],
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    page = await MultiFactorService.list_results(db, query)
    return ResponseUtil.success(model_content=page)


@multi_factor_controller.get(
    '/batch/latest',
    summary='查询最新批次信息',
    description='获取最新计算批次的总数/入选数/降级因子等',
    response_model=DataResponseModel[MultiFactorBatchInfoModel],
    dependencies=[UserInterfaceAuthDependency('stock:multiFactor:list')],
)
async def get_latest_batch(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await MultiFactorService.get_latest_batch(db)
    if result is None:
        return ResponseUtil.success(data=None, msg='暂无计算结果')
    return ResponseUtil.success(data=result)


@multi_factor_controller.get(
    '/weights',
    summary='查询因子权重配置',
    description='获取当前7个因子的权重配置',
    response_model=DataResponseModel[list[dict]],
    dependencies=[UserInterfaceAuthDependency('stock:multiFactor:list')],
)
async def get_factor_weights(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await MultiFactorService.get_factor_weights(db)
    return ResponseUtil.success(data=result)


@multi_factor_controller.post(
    '/pool/add',
    summary='入选股票加入股票池',
    description='将最新批次入选(>=90分)的股票批量加入指定股票池',
    response_model=DataResponseModel[MultiFactorPoolAddResultModel],
    dependencies=[UserInterfaceAuthDependency('stock:multiFactor:poolAdd')],
)
async def add_multi_factor_to_pool(
    request: Request,
    body: MultiFactorPoolAddRequestModel,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await MultiFactorService.add_selected_to_pool(db, body)
    logger.info(
        f'多因子选股加入股票池: pool={result.pool_name} 新增={result.added_count} '
        f'跳过={result.skipped_count}'
    )
    return ResponseUtil.success(data=result, msg='已加入股票池')

