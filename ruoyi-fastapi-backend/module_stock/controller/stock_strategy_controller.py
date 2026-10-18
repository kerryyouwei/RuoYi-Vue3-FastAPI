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
    StrategyTradesPageModel,
    StrategyValidateRequest,
    StrategyValidationModel,
    StrategyValidationQueryModel,
)
from module_stock.service.stock_strategy_service import StockStrategyService
from utils.log_util import logger
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

@stock_strategy_controller.get(
    '/run/{run_id}/trades',
    response_model=DataResponseModel[StrategyTradesPageModel],
    dependencies=[UserInterfaceAuthDependency('stock:strategy:detail')],
)
async def run_trades(
    request: Request,
    run_id: Annotated[str, Path()],
    db: Annotated[AsyncSession, DBSessionDependency()],
    trade_page_num: Annotated[int, Query(ge=1)] = 1,
    trade_page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Response:
    return ResponseUtil.success(
        data=await StockStrategyService.run_trades(db, run_id, trade_page_num, trade_page_size)
    )


@stock_strategy_controller.post(
    '/validate',
    summary='提交股票池滚动验证',
    description='按自然年窗口对组合策略做滚动样本外验证，参数全程冻结',
    response_model=DataResponseModel[dict],
    dependencies=[UserInterfaceAuthDependency('stock:strategy:run')],
)
async def validate_strategy(
    request: Request,
    body: StrategyValidateRequest,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    validation_id = await StockStrategyService.validate(db, body)
    logger.bind(
        validation_id=validation_id, strategy_name=body.strategy_name, pool_name=body.pool_name
    ).info('股票池滚动验证已提交')
    return ResponseUtil.success(data={'validationId': validation_id}, msg='滚动验证已提交')


@stock_strategy_controller.get(
    '/validation',
    summary='分页查询滚动验证历史',
    response_model=PageResponseModel,
    dependencies=[UserInterfaceAuthDependency('stock:strategy:detail')],
)
async def list_validations(
    request: Request,
    query: Annotated[StrategyValidationQueryModel, Query()],
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    return ResponseUtil.success(model_content=await StockStrategyService.validation_list(db, query))


@stock_strategy_controller.get(
    '/validation/{validation_id}',
    summary='查询滚动验证状态与结果',
    response_model=DataResponseModel[StrategyValidationModel],
    dependencies=[UserInterfaceAuthDependency('stock:strategy:detail')],
)
async def get_validation(
    request: Request,
    validation_id: Annotated[str, Path(max_length=36)],
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    return ResponseUtil.success(data=await StockStrategyService.validation_status(db, validation_id))


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
