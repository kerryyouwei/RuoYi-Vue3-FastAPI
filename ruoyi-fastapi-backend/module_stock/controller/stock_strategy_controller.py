from typing import Annotated

from fastapi import Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.aspect.db_session import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel
from module_stock.entity.vo.stock_strategy_vo import (
    StrategyDetailModel,
    StrategyHistoryQueryModel,
    StrategyListModel,
    StrategyQueryModel,
    StrategyRunDetailModel,
    StrategyRunRequest,
    StrategyRunStatusModel,
)
from module_stock.service.stock_strategy_service import StockStrategyService
from utils.response_util import ResponseUtil

stock_strategy_controller = APIRouterPro(
    prefix='/stock/strategy', order_num=19, tags=['股票管理-策略回测'], dependencies=[PreAuthDependency()]
)


@stock_strategy_controller.get('/list', response_model=DataResponseModel[list[StrategyListModel]], dependencies=[UserInterfaceAuthDependency('stock:strategy:list')])
async def list_strategies(
    request: Request,
    query: Annotated[StrategyQueryModel, Query()],
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    strategies = await StockStrategyService.list_strategies(db)
    filtered = [
        item for item in strategies
        if (not query.strategy_name or query.strategy_name.lower() in item.name.lower() or query.strategy_name.lower() in item.display_name.lower())
        and (not query.category or query.category == item.category)
        and (not query.status or query.status == item.last_status)
    ]
    return ResponseUtil.success(data=filtered)


@stock_strategy_controller.post('/run', response_model=DataResponseModel[dict], dependencies=[UserInterfaceAuthDependency('stock:strategy:run')])
async def run_strategy(
    request: Request, body: StrategyRunRequest, db: Annotated[AsyncSession, DBSessionDependency()]
) -> Response:
    return ResponseUtil.success(data={'runId': await StockStrategyService.create_run(db, body)}, msg='回测已提交')


@stock_strategy_controller.get('/run/{run_id}', response_model=DataResponseModel[StrategyRunStatusModel], dependencies=[UserInterfaceAuthDependency('stock:strategy:detail')])
async def run_status(request: Request, run_id: Annotated[str, Path()], db: Annotated[AsyncSession, DBSessionDependency()]) -> Response:
    return ResponseUtil.success(data=await StockStrategyService.status(db, run_id))


@stock_strategy_controller.get('/run/{run_id}/detail', response_model=DataResponseModel[StrategyRunDetailModel], dependencies=[UserInterfaceAuthDependency('stock:strategy:detail')])
async def run_detail(request: Request, run_id: Annotated[str, Path()], db: Annotated[AsyncSession, DBSessionDependency()]) -> Response:
    return ResponseUtil.success(data=await StockStrategyService.status(db, run_id, detail=True))


@stock_strategy_controller.get('/{strategy_name}/history', response_model=PageResponseModel, dependencies=[UserInterfaceAuthDependency('stock:strategy:detail')])
async def strategy_history(
    request: Request,
    strategy_name: Annotated[str, Path()],
    query: Annotated[StrategyHistoryQueryModel, Query()],
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    return ResponseUtil.success(model_content=await StockStrategyService.history(db, strategy_name, query))


@stock_strategy_controller.get('/{strategy_name}', response_model=DataResponseModel[StrategyDetailModel], dependencies=[UserInterfaceAuthDependency('stock:strategy:detail')])
async def strategy_detail(request: Request, strategy_name: Annotated[str, Path()]) -> Response:
    return ResponseUtil.success(data=await StockStrategyService.detail(strategy_name))
