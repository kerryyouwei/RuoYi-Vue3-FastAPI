from typing import Annotated

from fastapi import Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.aspect.db_session import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel, ResponseBaseModel
from module_stock.entity.vo.stock_paper_vo import (
    PaperAccountCreateModel,
    PaperAccountInitRequestModel,
    PaperAccountModel,
    PaperAccountUpdateModel,
    PaperOrderModel,
    PaperPageQueryModel,
    PaperPositionModel,
    PaperRealtimeQuoteModel,
    PaperSignalModel,
    PaperSignalRecallRequestModel,
    PaperSnapshotModel,
    PaperUniverseAddRequestModel,
    PaperUniverseAddResultModel,
    PaperUniverseLogModel,
    PaperUniverseLogQueryModel,
    PaperUniverseModel,
    PaperUniverseRemoveRequestModel,
    PaperUniverseRemoveResultModel,
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
    '/accounts',
    summary='查询全部模拟盘账户',
    description='返回所有模拟盘账户及其概览指标，用于前端账户切换',
    response_model=DataResponseModel[list[PaperAccountModel]],
    dependencies=[UserInterfaceAuthDependency('stock:paper:list')],
)
async def list_paper_accounts(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    return ResponseUtil.success(data=await StockPaperService.list_accounts(db))


@stock_paper_controller.post(
    '/account/create',
    summary='新建模拟盘账户',
    description='按名称创建新的模拟盘账户（不重置既有账户），可同时写入初始标的池',
    response_model=DataResponseModel[PaperAccountModel],
    dependencies=[UserInterfaceAuthDependency('stock:paper:account')],
)
async def create_paper_account(
    request: Request,
    body: PaperAccountCreateModel,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await StockPaperService.create_account(db, body)
    logger.bind(account_name=body.account_name).info('模拟盘账户创建完成')
    return ResponseUtil.success(data=result, msg='模拟盘账户创建完成')


@stock_paper_controller.put(
    '/account/{account_id}',
    summary='更新模拟盘账户',
    description='更新账户策略或启停状态（inactive 后定时任务不再处理该账户）',
    response_model=DataResponseModel[PaperAccountModel],
    dependencies=[UserInterfaceAuthDependency('stock:paper:account')],
)
async def update_paper_account(
    request: Request,
    account_id: int,
    body: PaperAccountUpdateModel,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    return ResponseUtil.success(data=await StockPaperService.update_account_fields(db, account_id, body))


@stock_paper_controller.delete(
    '/account/{account_id}',
    summary='删除模拟盘账户',
    description='删除账户及其标的池/信号/持仓/成交/净值历史；仍有持仓时需 force=true 强制删除',
    response_model=DataResponseModel[dict],
    dependencies=[UserInterfaceAuthDependency('stock:paper:account')],
)
async def delete_paper_account(
    request: Request,
    account_id: int,
    db: Annotated[AsyncSession, DBSessionDependency()],
    force: Annotated[bool, Query()] = False,
) -> Response:
    result = await StockPaperService.delete_account(db, account_id, force)
    return ResponseUtil.success(data=result, msg='模拟盘账户已删除')

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
    account_name: Annotated[str, Query(alias='accountName', max_length=64)] = DEFAULT_ACCOUNT_NAME,
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
    account_name: Annotated[str, Query(alias='accountName', max_length=64)] = DEFAULT_ACCOUNT_NAME,
    status: Annotated[str, Query(description='active/inactive/all')] = 'active',
) -> Response:
    return ResponseUtil.success(data=await StockPaperService.list_universe(db, account_name, status))


@stock_paper_controller.post(
    '/universe/add',
    summary='动态加入标的池',
    description='支持直接代码、整池加入（poolName）与从原始池勾选（poolCodes）三种方式；已 active 标的自动跳过',
    response_model=DataResponseModel[PaperUniverseAddResultModel],
    dependencies=[UserInterfaceAuthDependency('stock:paper:universe:add')],
)
async def add_paper_universe(
    request: Request,
    body: PaperUniverseAddRequestModel,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await StockPaperService.add_to_universe(db, body)
    logger.bind(
        account_name=body.account_name, added_count=result['addedCount'], skipped_count=result['skippedCount']
    ).info('模拟盘标的池动态加入')
    return ResponseUtil.success(data=result, msg='标的池加入完成')


@stock_paper_controller.post(
    '/universe/remove',
    summary='动态移出标的池',
    description='逻辑停用指定标的；任一标的持仓中则整体拒绝（提示持仓中不允许移出）',
    response_model=DataResponseModel[PaperUniverseRemoveResultModel],
    dependencies=[UserInterfaceAuthDependency('stock:paper:universe:remove')],
)
async def remove_paper_universe(
    request: Request,
    body: PaperUniverseRemoveRequestModel,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await StockPaperService.remove_from_universe(db, body)
    logger.bind(account_name=body.account_name, removed_count=result['removedCount']).info('模拟盘标的池动态移出')
    return ResponseUtil.success(data=result, msg='标的池移出完成')


@stock_paper_controller.get(
    '/universe/log',
    summary='分页查询标的池变更日志',
    description='分页浏览标的池加入/移出记录（含来源与时间）',
    response_model=PageResponseModel[PaperUniverseLogModel],
    dependencies=[UserInterfaceAuthDependency('stock:paper:list')],
)
async def get_paper_universe_logs(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
    query: Annotated[PaperUniverseLogQueryModel, Query()],
) -> Response:
    return ResponseUtil.success(
        model_content=await StockPaperService.list_universe_logs(
            db, query.account_name, query.code, query.page_num, query.page_size
        )
    )


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
    account_name: Annotated[str, Query(alias='accountName', max_length=64)] = DEFAULT_ACCOUNT_NAME,
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
    account_name: Annotated[str, Query(alias='accountName', max_length=64)] = DEFAULT_ACCOUNT_NAME,
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
async def run_paper_signal(
    request: Request,
    account_name: Annotated[str | None, Query(alias='accountName', max_length=64)] = None,
) -> Response:
    await StockPaperService.run_eod_signal(account_name)
    return ResponseUtil.success(msg='收盘信号计算完成')


@stock_paper_controller.post(
    '/execute/run',
    summary='手动触发开盘撮合',
    description='对 execute_date 为今日的待执行信号按开盘价撮合并写入成交记录',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('stock:paper:execute')],
)
async def run_paper_execute(
    request: Request,
    account_name: Annotated[str | None, Query(alias='accountName', max_length=64)] = None,
) -> Response:
    await StockPaperService.run_morning_execute(account_name)
    return ResponseUtil.success(msg='开盘撮合完成')


@stock_paper_controller.post(
    '/realtime/run',
    summary='手动触发实时轮循',
    description='交易时段内按实时行情计算模拟盘信号，信号变化立即自动撮合并刷新净值快照',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('stock:paper:execute')],
)
async def run_paper_realtime(
    request: Request,
    account_name: Annotated[str | None, Query(alias='accountName', max_length=64)] = None,
) -> Response:
    result = await StockPaperService.run_realtime_signal_and_execute(account_name)
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
    account_name: Annotated[str, Query(alias='accountName', max_length=64)] = DEFAULT_ACCOUNT_NAME,
) -> Response:
    return ResponseUtil.success(data=await StockPaperService.get_realtime_quotes(db, account_name))


@stock_paper_controller.post(
    '/daily-sync/run',
    summary='手动触发标的池日线同步',
    description='开盘前同步模拟盘标的池所有股票的日线数据到MongoDB，确保收盘信号使用最新K线',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('stock:paper:execute')],
)
async def run_paper_daily_sync(
    request: Request,
    account_name: Annotated[str | None, Query(alias='accountName', max_length=64)] = None,
) -> Response:
    result = await StockPaperService.run_daily_sync(account_name)
    return ResponseUtil.success(msg=result.get('message', '日线同步完成'))
