from typing import Annotated

from fastapi import Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.aspect.db_session import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel, ResponseBaseModel
from module_stock.entity.vo.stock_paper_vo import (
    PaperAccountInitRequestModel,
    PaperAccountModel,
    PaperOrderModel,
    PaperPageQueryModel,
    PaperPositionModel,
    PaperRealtimeQuoteModel,
    PaperSignalModel,
    PaperSignalRecallRequestModel,
    PaperSnapshotModel,
    PaperUniverseModel,
)
from module_stock.service.stock_paper_service import DEFAULT_ACCOUNT_NAME, StockPaperService
from utils.log_util import logger
from utils.response_util import ResponseUtil

stock_paper_controller = APIRouterPro(
    prefix='/stock/paper', order_num=21, tags=['股票管理-模拟交易'], dependencies=[PreAuthDependency()]
)


@stock_paper_controller.post(
    '/account/init',
    summary='初始化模拟盘账户',
    description='重置现金、清空历史交易，并按策略初始资金与标的代码重写标的池',
    response_model=DataResponseModel[dict],
    dependencies=[UserInterfaceAuthDependency('stock:paper:account')],
)
async def init_paper_account(
    request: Request,
    body: PaperAccountInitRequestModel,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await StockPaperService.init_account(db, body)
    logger.bind(account_name=body.account_name, added_count=result['addedCount']).info('模拟盘账户初始化完成')
    return ResponseUtil.success(data=result, msg='模拟盘账户初始化完成')


@stock_paper_controller.get(
    '/account',
    summary='查询模拟盘账户概览',
    description='返回总资产、现金、持仓市值、累计收益等账户概览指标',
    response_model=DataResponseModel[PaperAccountModel],
    dependencies=[UserInterfaceAuthDependency('stock:paper:list')],
)
async def get_paper_account(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
    account_name: Annotated[str, Query(max_length=64)] = DEFAULT_ACCOUNT_NAME,
) -> Response:
    return ResponseUtil.success(data=await StockPaperService.get_account(db, account_name))


@stock_paper_controller.get(
    '/universe',
    summary='查询模拟盘标的池',
    description='返回当前标的池中的股票（含来源回测批次），持仓产生前的核对入口',
    response_model=DataResponseModel[list[PaperUniverseModel]],
    dependencies=[UserInterfaceAuthDependency('stock:paper:list')],
)
async def get_paper_universe(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
    account_name: Annotated[str, Query(max_length=64)] = DEFAULT_ACCOUNT_NAME,
) -> Response:
    return ResponseUtil.success(data=await StockPaperService.list_universe(db, account_name))


@stock_paper_controller.get(
    '/positions',
    summary='查询模拟盘持仓',
    description='返回模拟盘当前持仓列表（含市值与浮动盈亏）',
    response_model=DataResponseModel[list[PaperPositionModel]],
    dependencies=[UserInterfaceAuthDependency('stock:paper:position')],
)
async def get_paper_positions(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
    account_name: Annotated[str, Query(max_length=64)] = DEFAULT_ACCOUNT_NAME,
) -> Response:
    return ResponseUtil.success(data=await StockPaperService.list_positions(db, account_name))


@stock_paper_controller.get(
    '/signals',
    summary='分页查询交易信号',
    description='分页浏览模拟盘每日产出的买入/卖出/持有信号',
    response_model=PageResponseModel[PaperSignalModel],
    dependencies=[UserInterfaceAuthDependency('stock:paper:list')],
)
async def get_paper_signals(
    request: Request,
    query: Annotated[PaperPageQueryModel, Query()],
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    return ResponseUtil.success(
        model_content=await StockPaperService.list_signals(db, query.account_name, query.page_num, query.page_size)
    )


@stock_paper_controller.post(
    '/signals/{signal_id}/recall',
    summary='撤回交易信号飞书通知',
    description='根据已保存的飞书message_id撤回企业自建应用机器人发送的实时交易信号',
    response_model=DataResponseModel[dict],
    dependencies=[UserInterfaceAuthDependency('stock:paper:signal')],
)
async def recall_paper_signal_notification(
    request: Request,
    signal_id: int,
    body: PaperSignalRecallRequestModel,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await StockPaperService.recall_signal_notification(db, signal_id, body.reason)
    if result.get('status') != 'recalled':
        return ResponseUtil.failure(msg=result.get('error_message') or '飞书通知撤回失败', data=result)
    return ResponseUtil.success(msg='飞书通知已撤回', data=result)


@stock_paper_controller.get(
    '/orders',
    summary='分页查询成交/跳过记录',
    description='分页浏览模拟盘成交记录（含跳过原因）',
    response_model=PageResponseModel[PaperOrderModel],
    dependencies=[UserInterfaceAuthDependency('stock:paper:list')],
)
async def get_paper_orders(
    request: Request,
    query: Annotated[PaperPageQueryModel, Query()],
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    return ResponseUtil.success(
        model_content=await StockPaperService.list_orders(db, query.account_name, query.page_num, query.page_size)
    )


@stock_paper_controller.get(
    '/snapshot',
    summary='查询模拟盘净值快照',
    description='返回用于前端净值曲线展示的每日净值快照列表',
    response_model=DataResponseModel[list[PaperSnapshotModel]],
    dependencies=[UserInterfaceAuthDependency('stock:paper:list')],
)
async def get_paper_snapshot(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
    account_name: Annotated[str, Query(max_length=64)] = DEFAULT_ACCOUNT_NAME,
    start_date: Annotated[str | None, Query(max_length=10)] = None,
    end_date: Annotated[str | None, Query(max_length=10)] = None,
) -> Response:
    return ResponseUtil.success(data=await StockPaperService.list_snapshot(db, account_name, start_date, end_date))


@stock_paper_controller.post(
    '/signal/run',
    summary='手动触发收盘信号计算',
    description='对模拟盘标的池逐只计算当日信号，并写入 signal 表（次日开盘执行）',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('stock:paper:signal')],
)
async def run_paper_signal(request: Request) -> Response:
    await StockPaperService.run_eod_signal()
    return ResponseUtil.success(msg='收盘信号计算完成')


@stock_paper_controller.post(
    '/execute/run',
    summary='手动触发开盘撮合',
    description='对 execute_date 为今日的待执行信号按开盘价撮合并写入成交记录',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('stock:paper:execute')],
)
async def run_paper_execute(request: Request) -> Response:
    await StockPaperService.run_morning_execute()
    return ResponseUtil.success(msg='开盘撮合完成')


@stock_paper_controller.post(
    '/realtime/run',
    summary='手动触发实时轮循',
    description='交易时段内按实时行情计算模拟盘信号，信号变化立即自动撮合并刷新净值快照',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('stock:paper:execute')],
)
async def run_paper_realtime(request: Request) -> Response:
    result = await StockPaperService.run_realtime_signal_and_execute()
    return ResponseUtil.success(msg=result.get('message', '实时轮循执行完成'))


@stock_paper_controller.get(
    '/realtime-quotes',
    summary='查询标的池实时行情',
    description='返回标的池每只股票的实时价格与持仓浮动盈亏',
    response_model=DataResponseModel[list[PaperRealtimeQuoteModel]],
    dependencies=[UserInterfaceAuthDependency('stock:paper:list')],
)
async def get_paper_realtime_quotes(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
    account_name: Annotated[str, Query(max_length=64)] = DEFAULT_ACCOUNT_NAME,
) -> Response:
    return ResponseUtil.success(data=await StockPaperService.get_realtime_quotes(db, account_name))


@stock_paper_controller.post(
    '/daily-sync/run',
    summary='手动触发标的池日线同步',
    description='开盘前同步模拟盘标的池所有股票的日线数据到MongoDB，确保收盘信号使用最新K线',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('stock:paper:execute')],
)
async def run_paper_daily_sync(request: Request) -> Response:
    result = await StockPaperService.run_daily_sync()
    return ResponseUtil.success(msg=result.get('message', '日线同步完成'))
