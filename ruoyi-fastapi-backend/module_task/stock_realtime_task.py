"""股票实时行情采集与 Jk MA5 突破信号定时任务。"""

from module_stock.service.stock_realtime_service import StockRealtimeService
from utils.log_util import logger

# 实盘监控股票池：固定小池子先跑通链路，后续扩展全市场时再调整
WATCH_CODES = ['000001']
REALTIME_PACKAGE = 'tdx'


async def collect_stock_realtime_and_signal(
    codes: list[str] | None = None,
    package: str = REALTIME_PACKAGE,
) -> None:
    """
    每个交易日收盘后采集实时行情写入MongoDB，并按 Jk MA5 突破规则打印交易信号日志

    :param codes: 股票代码列表，默认使用 WATCH_CODES 固定股票池
    :param package: QUANTAXIS 实时行情数据源，默认 tdx
    :return: None
    """
    result = await StockRealtimeService.collect_and_signal(
        codes=codes if codes else WATCH_CODES,
        package=package,
    )
    logger.bind(task_name='collect_stock_realtime_and_signal', result=result).info(result['message'])
