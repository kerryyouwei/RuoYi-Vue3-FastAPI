"""模拟盘收盘信号计算与开盘撮合定时任务。"""

from module_stock.service.stock_paper_service import StockPaperService
from utils.log_util import logger


async def run_stock_paper_eod_signal() -> None:
    """每个交易日 15:05 收盘后计算模拟盘交易信号。"""
    await StockPaperService.run_eod_signal()
    logger.bind(task_name='run_stock_paper_eod_signal').info('模拟盘收盘信号任务执行完成')


async def run_stock_paper_morning_execute() -> None:
    """每个交易日 09:35 开盘后按前一交易日信号撮合模拟交易。"""
    await StockPaperService.run_morning_execute()
    logger.bind(task_name='run_stock_paper_morning_execute').info('模拟盘开盘撮合任务执行完成')


async def run_stock_paper_realtime() -> None:
    """交易时段每分钟轮循模拟盘标的池实时行情并自动撮合。"""
    await StockPaperService.run_realtime_signal_and_execute()
    logger.bind(task_name='run_stock_paper_realtime').info('模拟盘实时轮循任务执行完成')


async def run_stock_paper_daily_sync() -> None:
    """每个交易日09:15开盘前同步标的池日线数据到MongoDB。"""
    await StockPaperService.run_daily_sync()
    logger.bind(task_name='run_stock_paper_daily_sync').info('标的池日线同步任务执行完成')
