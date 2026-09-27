from typing import Annotated

from fastapi import Query, Request, Response

from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel
from module_stock.entity.vo.stock_day_vo import (
    StockDayImportModel,
    StockDayImportResultModel,
    StockDayModel,
    StockDayQueryModel,
)
from module_stock.service.stock_day_service import StockDayService
from utils.log_util import logger
from utils.response_util import ResponseUtil

stock_day_controller = APIRouterPro(
    prefix='/stock/day', order_num=18, tags=['股票管理-日线行情'], dependencies=[PreAuthDependency()]
)


@stock_day_controller.get(
    '/list',
    summary='获取股票日线数据接口',
    description='用于从QUANTAXIS使用的MongoDB中获取指定股票和日期范围的日线数据',
    response_model=PageResponseModel[StockDayModel],
)
async def get_stock_day_list(
    request: Request,
    stock_day_query: Annotated[StockDayQueryModel, Query()],
) -> Response:
    stock_day_page = await StockDayService.get_stock_day_list(stock_day_query)
    logger.info(
        f'获取股票{stock_day_query.code}从{stock_day_query.start}至{stock_day_query.end}的日线数据成功，'
        f'第{stock_day_query.page_num}页，共{stock_day_page.total}条'
    )

    return ResponseUtil.success(model_content=stock_day_page)


@stock_day_controller.post(
    '/import',
    summary='导入股票日线数据接口',
    description='用于从Baostock获取股票日线数据并写入QUANTAXIS使用的MongoDB',
    response_model=DataResponseModel[StockDayImportResultModel],
)
async def import_stock_day_data(
    request: Request,
    stock_day_query: Annotated[StockDayImportModel, Query()],
) -> Response:
    import_result = await StockDayService.import_stock_day_data(stock_day_query)
    logger.info(import_result.message)

    return ResponseUtil.success(data=import_result, msg=import_result.message)
