from typing import Annotated

from fastapi import Query, Request, Response

from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel
from module_stock.entity.vo.stock_list_vo import (
    StockListImportResultModel,
    StockListModel,
    StockListQueryModel,
)
from module_stock.service.stock_list_service import StockListService
from utils.log_util import logger
from utils.response_util import ResponseUtil

stock_list_controller = APIRouterPro(
    prefix='/stock/list', order_num=20, tags=['股票管理-股票列表'], dependencies=[PreAuthDependency()]
)


@stock_list_controller.get(
    '/list',
    summary='获取A股股票列表接口',
    description='用于从QUANTAXIS使用的MongoDB中分页查询A股股票列表',
    response_model=PageResponseModel[StockListModel],
)
async def get_stock_list(
    request: Request,
    stock_list_query: Annotated[StockListQueryModel, Query()],
) -> Response:
    stock_list_page = await StockListService.get_stock_list(stock_list_query)
    logger.info(
        f'获取股票列表成功，第{stock_list_query.page_num}页，共{stock_list_page.total}条'
    )

    return ResponseUtil.success(model_content=stock_list_page)


@stock_list_controller.post(
    '/import',
    summary='导入A股股票列表接口',
    description='用于从Baostock获取A股股票列表并写入QUANTAXIS使用的MongoDB',
    response_model=DataResponseModel[StockListImportResultModel],
)
async def import_stock_list_data(
    request: Request,
) -> Response:
    import_result = await StockListService.import_stock_list()
    logger.info(import_result.message)

    return ResponseUtil.success(data=import_result, msg=import_result.message)
