
"""股票池 DDE 大单资金通知定时任务。"""

from module_stock.service.stock_dde_notify_service import StockDDENotifyService
from utils.log_util import logger


async def send_stock_pool_dde_notify(pool_name: str = 'default', top_n: int = 30, force: bool = False) -> None:
    """交易日交易时段每小时推送全账户标的池DDE大单资金通知；force=True可绕过非交易日限制。"""
    logger.bind(task_name='send_stock_pool_dde_notify', pool_name=pool_name, top_n=top_n, force=force).info('DDE通知任务开始执行')
    result = await StockDDENotifyService.send_pool_dde_notification(pool_name=pool_name, top_n=top_n, force=force)
    logger.bind(task_name='send_stock_pool_dde_notify', **result).info(result.get('message') or 'DDE通知任务执行完成')
