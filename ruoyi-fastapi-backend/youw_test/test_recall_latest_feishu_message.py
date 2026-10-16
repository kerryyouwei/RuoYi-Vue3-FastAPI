"""手动撤回最近一条已发送的飞书消息。

用法（在 ruoyi-fastapi-backend 目录执行）：
    python -m youw_test.test_recall_latest_feishu_message
"""

import asyncio
import json
from datetime import datetime

from sqlalchemy import select, update

from config.database import DataSourceRegistry
from config.env import FeishuNotifyConfig
from module_stock.entity.do.stock_paper_do import StockFeishuMessage
from module_stock.service.stock_feishu_notification_service import FeishuNotificationService
from utils.log_util import logger
from utils.time_util import TimezoneUtil


class RecallLatestSentMessageTester:
    """查询并撤回最近一条已发送的飞书消息。"""

    def __init__(self, message_type: str | None = None, reason: str = '测试撤回最近发送的飞书消息') -> None:
        """message_type 为空时不过滤类型，默认撤回最近发送的任意飞书消息。"""
        self.message_type = message_type
        self.reason = reason

    async def _get_latest_sent_message(self) -> StockFeishuMessage | None:
        """读取最近一条待撤回的飞书消息凭据。"""
        async with DataSourceRegistry.session(log_sql=False) as db:
            stmt = (
                select(StockFeishuMessage)
                .where(StockFeishuMessage.recall_status == 'sent')
                .order_by(StockFeishuMessage.id.desc())
                .limit(1)
            )
            if self.message_type:
                stmt = stmt.where(StockFeishuMessage.message_type == self.message_type)
            return ((await db.execute(stmt)).scalars().first())

    async def _update_message(self, message_id: int, **values: object) -> None:
        """同步保存撤回结果，便于后续审计和避免重复撤回。"""
        async with DataSourceRegistry.session(log_sql=False) as db:
            await db.execute(update(StockFeishuMessage).where(StockFeishuMessage.id == message_id).values(**values))
            await db.commit()

    async def run(self) -> dict[str, object]:
        """撤回最近一条飞书消息并返回执行结果。"""
        await DataSourceRegistry.initialize(log_enabled=False)
        try:
            message = await self._get_latest_sent_message()
            if message is None:
                return {'ok': False, 'status': 'not_found', 'message': '没有待撤回的飞书消息'}
            if not message.message_id:
                return {'ok': False, 'status': 'missing_message_id', 'message': '飞书消息凭据缺少message_id'}

            recall_result = await FeishuNotificationService.recall_message(message.message_id)
            if recall_result.ok:
                await self._update_message(
                    message.id,
                    recall_status='recalled',
                    recall_reason=self.reason,
                    recalled_at=datetime.now(TimezoneUtil.get_app_timezone()),
                )
                return {
                    'ok': True,
                    'status': 'recalled',
                    'record_id': message.id,
                    'message_id': message.message_id,
                    'message_type': message.message_type,
                }

            error_message = recall_result.error_message or '飞书消息撤回失败'
            await self._update_message(message.id, recall_status='failed', recall_reason=error_message[:500])
            return {
                'ok': False,
                'status': 'failed',
                'record_id': message.id,
                'message_id': message.message_id,
                'message_type': message.message_type,
                'message': error_message,
            }
        finally:
            await DataSourceRegistry.dispose_all()


async def main() -> None:
    """执行撤回测试。"""
    if not FeishuNotifyConfig.feishu_notify_enabled:
        logger.warning('飞书通知未启用，跳过撤回测试')
        return
    result = await RecallLatestSentMessageTester().run()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    asyncio.run(main())
