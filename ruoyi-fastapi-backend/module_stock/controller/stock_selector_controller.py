from typing import Annotated

from fastapi import Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.aspect.db_session import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel, ResponseBaseModel
from module_stock.entity.vo.stock_selector_vo import (
    AStockSearchResultModel,
    SelectorSearchQueryModel,
    StockPoolAddRequestModel,
    StockPoolAddResultModel,
    StockPoolItemModel,
    StockPoolNameModel,
    StockPoolQueryModel,
)
from module_stock.service.stock_selector_service import StockSelectorService
from utils.log_util import logger
from utils.response_util import ResponseUtil

stock_selector_controller = APIRouterPro(
    prefix='/stock/selector', order_num=17, tags=['股票管理-智能选股'], dependencies=[PreAuthDependency()]
)


@stock_selector_controller.get(
    '/search',
    summary='问财智能选股查询接口',
    description='根据结构化条件和自定义问句调用同花顺问财进行A股筛选',
    response_model=DataResponseModel[AStockSearchResultModel],
    dependencies=[UserInterfaceAuthDependency('stock:selector:query')],
)
async def search_stocks(
    request: Request,
    query: Annotated[SelectorSearchQueryModel, Query()],
) -> Response:
    result = await StockSelectorService.search(query)
    logger.info(f'问财选股查询成功，实际条件：{result.query_text}，第{query.page_num}页，共{result.code_count}条')
    return ResponseUtil.success(data=result)


@stock_selector_controller.post(
    '/pool/add',
    summary='加入股票池接口',
    description='将选股结果批量加入指定股票池，同一池内自动跳过重复股票',
    response_model=DataResponseModel[StockPoolAddResultModel],
    dependencies=[UserInterfaceAuthDependency('stock:pool:add')],
)
async def add_stock_pool_items(
    request: Request, body: StockPoolAddRequestModel, db: Annotated[AsyncSession, DBSessionDependency()]
) -> Response:
    result = await StockSelectorService.add_to_pool(db, body)
    logger.info(
        f'股票池{result.pool_name}新增{result.added_count}只股票，跳过{result.skipped_count}只，'
        f'请求{result.requested_count}只'
    )
    return ResponseUtil.success(data=result, msg='已加入股票池')


@stock_selector_controller.get(
    '/pool/list',
    summary='查询股票池接口',
    description='分页查询指定股票池中的股票',
    response_model=PageResponseModel[StockPoolItemModel],
    dependencies=[UserInterfaceAuthDependency('stock:pool:list')],
)
async def get_stock_pool_list(
    request: Request,
    query: Annotated[StockPoolQueryModel, Query()],
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    page = await StockSelectorService.pool_list(db, query)
    return ResponseUtil.success(model_content=page)


@stock_selector_controller.get(
    '/pool/names',
    summary='查询股票池名称接口',
    description='查询已有股票池名称及股票数量',
    response_model=DataResponseModel[list[StockPoolNameModel]],
    dependencies=[UserInterfaceAuthDependency('stock:pool:list')],
)
async def get_stock_pool_names(
    request: Request, db: Annotated[AsyncSession, DBSessionDependency()]
) -> Response:
    return ResponseUtil.success(data=await StockSelectorService.pool_names(db))


@stock_selector_controller.delete(
    '/pool/{item_id}',
    summary='删除股票池记录接口',
    description='从指定股票池中删除一条股票记录',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('stock:pool:remove')],
)
async def remove_stock_pool_item(
    request: Request,
    item_id: Annotated[int, Path(ge=1)],
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    await StockSelectorService.remove_pool_item(db, item_id)
    return ResponseUtil.success(msg='删除成功')
