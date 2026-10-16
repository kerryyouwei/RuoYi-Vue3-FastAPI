"""飞书交易信号通知服务，支持企业自建应用机器人消息发送与撤回。"""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import ClassVar

import httpx

from config.env import FeishuNotifyConfig
from utils.log_util import logger

FEISHU_BASE_URL = 'https://open.feishu.cn'
TOKEN_URL = f'{FEISHU_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal'
MESSAGE_URL = f'{FEISHU_BASE_URL}/open-apis/im/v1/messages'


@dataclass(frozen=True)
class FeishuSignal:
    """用于飞书通知的模拟盘交易信号。"""

    code: str
    signal: str
    reason: str
    name: str | None = None
    price: float | None = None
    time: str | None = None
    signal_id: int | None = None
    account_id: int | None = None


@dataclass(frozen=True)
class FeishuSendResult:
    """飞书消息发送结果，企业自建应用模式会返回 message_id。"""

    ok: bool
    message_id: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class FeishuRecallResult:
    """飞书消息撤回结果。"""

    ok: bool
    message_id: str
    error_message: str | None = None


class FeishuNotificationService:
    """发送模拟盘交易信号到飞书企业自建应用机器人，并支持撤回已发送消息。"""

    _app_token: ClassVar[str | None] = None
    _app_token_expire_at: ClassVar[float] = 0.0

    @staticmethod
    def _build_sign(timestamp: int, secret: str) -> str:
        """按飞书自定义机器人规则生成签名。"""
        string_to_sign = f'{timestamp}\n{secret}'
        digest = hmac.new(string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
        return base64.b64encode(digest).decode('utf-8')

    @classmethod
    def _build_payload(cls, text: str) -> dict[str, str | dict[str, str] | int]:
        """构造自定义机器人文本消息负载；签名密钥存在时附加签名参数。"""
        payload: dict[str, str | dict[str, str] | int] = {
            'msg_type': 'text',
            'content': {'text': text},
        }
        secret = FeishuNotifyConfig.feishu_notify_secret
        if secret:
            timestamp = int(time.time())
            payload['timestamp'] = timestamp
            payload['sign'] = cls._build_sign(timestamp, secret)
        return payload

    @staticmethod
    def _response_code(body: dict[str, object]) -> object:
        """兼容飞书接口响应字段。"""
        code = body.get('code')
        if code is None:
            return body.get('StatusCode')
        return code

    @classmethod
    async def _get_app_token(cls, client: httpx.AsyncClient) -> str:
        """获取并缓存企业自建应用的 tenant_access_token。"""
        if cls._app_token and time.monotonic() < cls._app_token_expire_at:
            return cls._app_token

        response = await client.post(
            TOKEN_URL,
            json={
                'app_id': FeishuNotifyConfig.feishu_app_id,
                'app_secret': FeishuNotifyConfig.feishu_app_secret,
            },
        )
        body = response.json()
        if response.status_code != httpx.codes.OK:
            logger.bind(channel='feishu', status_code=response.status_code).error(
                f'获取飞书访问凭证HTTP错误：{response.status_code} 响应体：{body}'
            )
            raise ValueError(f'获取飞书访问凭证HTTP {response.status_code}：{body}')
        if cls._response_code(body) != 0 or not body.get('tenant_access_token'):
            raise ValueError(f'获取飞书访问凭证失败：{body}')

        token = str(body['tenant_access_token'])
        expire_seconds = max(int(body.get('expire') or 7200) - 60, 60)
        cls._app_token = token
        cls._app_token_expire_at = time.monotonic() + expire_seconds
        return token

    @classmethod
    async def _send_app_text(
        cls, text: str, timeout: float, client_factory: type[httpx.AsyncClient] | None = None
    ) -> FeishuSendResult:
        """通过企业自建应用机器人发送消息。"""
        if not FeishuNotifyConfig.feishu_app_id or not FeishuNotifyConfig.feishu_app_secret:
            return FeishuSendResult(False, error_message='飞书应用ID或应用密钥未配置')
        if not FeishuNotifyConfig.feishu_chat_id:
            return FeishuSendResult(False, error_message='飞书接收ID未配置')

        factory = client_factory or httpx.AsyncClient
        try:
            async with factory(timeout=timeout) as client:
                token = await cls._get_app_token(client)
                response = await client.post(
                    MESSAGE_URL,
                    params={'receive_id_type': FeishuNotifyConfig.feishu_receive_id_type},
                    headers={'Authorization': f'Bearer {token}'},
                    json={
                        'receive_id': FeishuNotifyConfig.feishu_chat_id,
                        'msg_type': 'text',
                        'content': json.dumps({'text': text}, ensure_ascii=False, separators=(',', ':')),
                    },
                )
                body = response.json()
                if response.status_code != httpx.codes.OK:
                    logger.bind(channel='feishu', status_code=response.status_code).error(
                        f'飞书应用通知HTTP错误：{response.status_code} 响应体：{body}'
                    )
                    return FeishuSendResult(False, error_message=f'飞书API返回HTTP {response.status_code}：{body}')
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.bind(channel='feishu').error(f'飞书应用通知发送失败：{exc}')
            return FeishuSendResult(False, error_message=str(exc))

        if cls._response_code(body) != 0:
            logger.bind(channel='feishu', response_code=cls._response_code(body)).error(f'飞书应用通知返回失败：{body}')
            return FeishuSendResult(False, error_message=str(body.get('msg') or body))

        message_id = (body.get('data') or {}).get('message_id') if isinstance(body.get('data'), dict) else None
        if not message_id:
            logger.bind(channel='feishu').error(f'飞书应用通知缺少message_id：{body}')
            return FeishuSendResult(False, error_message='飞书应用通知返回缺少message_id')

        logger.bind(channel='feishu', message_id=message_id).info('飞书应用通知发送成功')
        return FeishuSendResult(True, message_id=str(message_id))

    @classmethod
    async def _send_webhook_text(cls, text: str, timeout: float) -> FeishuSendResult:
        """通过旧的自定义群机器人Webhook发送消息。"""
        webhook_url = FeishuNotifyConfig.feishu_notify_webhook_url.strip()
        if not webhook_url:
            return FeishuSendResult(False, error_message='飞书Webhook未配置')

        payload = cls._build_payload(text)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.bind(channel='feishu').error(f'飞书通知发送失败：{exc}')
            return FeishuSendResult(False, error_message=str(exc))

        if cls._response_code(body) != 0:
            logger.bind(channel='feishu', response_code=cls._response_code(body)).error(f'飞书通知返回失败：{body}')
            return FeishuSendResult(False, error_message=str(body.get('msg') or body))

        logger.bind(channel='feishu').info('飞书通知发送成功')
        return FeishuSendResult(True)

    @classmethod
    async def _send_app_card(
        cls, card: dict[str, object], timeout: float, client_factory: type[httpx.AsyncClient] | None = None
    ) -> FeishuSendResult:
        """通过企业自建应用机器人发送interactive卡片消息。"""
        if not FeishuNotifyConfig.feishu_app_id or not FeishuNotifyConfig.feishu_app_secret:
            return FeishuSendResult(False, error_message='飞书应用ID或应用密钥未配置')
        if not FeishuNotifyConfig.feishu_chat_id:
            return FeishuSendResult(False, error_message='飞书接收ID未配置')

        factory = client_factory or httpx.AsyncClient
        try:
            async with factory(timeout=timeout) as client:
                token = await cls._get_app_token(client)
                response = await client.post(
                    MESSAGE_URL,
                    params={'receive_id_type': FeishuNotifyConfig.feishu_receive_id_type},
                    headers={'Authorization': f'Bearer {token}'},
                    json={
                        'receive_id': FeishuNotifyConfig.feishu_chat_id,
                        'msg_type': 'interactive',
                        'content': json.dumps(card, ensure_ascii=False, separators=(',', ':')),
                    },
                )
                body = response.json()
                if response.status_code != httpx.codes.OK:
                    logger.bind(channel='feishu', status_code=response.status_code).error(
                        f'飞书卡片通知HTTP错误：{response.status_code} 响应体：{body}'
                    )
                    return FeishuSendResult(False, error_message=f'飞书API返回HTTP {response.status_code}：{body}')
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.bind(channel='feishu').error(f'飞书卡片通知发送失败：{exc}')
            return FeishuSendResult(False, error_message=str(exc))

        if cls._response_code(body) != 0:
            logger.bind(channel='feishu', response_code=cls._response_code(body)).error(f'飞书卡片通知返回失败：{body}')
            return FeishuSendResult(False, error_message=str(body.get('msg') or body))

        message_id = (body.get('data') or {}).get('message_id') if isinstance(body.get('data'), dict) else None
        if not message_id:
            logger.bind(channel='feishu').error(f'飞书卡片通知缺少message_id：{body}')
            return FeishuSendResult(False, error_message='飞书卡片通知返回缺少message_id')

        logger.bind(channel='feishu', message_id=message_id).info('飞书卡片通知发送成功')
        return FeishuSendResult(True, message_id=str(message_id))

    @classmethod
    async def _send_webhook_card(cls, card: dict[str, object], timeout: float) -> FeishuSendResult:
        """通过自定义群机器人Webhook发送interactive卡片消息。"""
        webhook_url = FeishuNotifyConfig.feishu_notify_webhook_url.strip()
        if not webhook_url:
            return FeishuSendResult(False, error_message='飞书Webhook未配置')

        payload: dict[str, object] = {'msg_type': 'interactive', 'card': card}
        secret = FeishuNotifyConfig.feishu_notify_secret
        if secret:
            timestamp = int(time.time())
            payload['timestamp'] = timestamp
            payload['sign'] = cls._build_sign(timestamp, secret)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.bind(channel='feishu').error(f'飞书卡片通知发送失败：{exc}')
            return FeishuSendResult(False, error_message=str(exc))

        if cls._response_code(body) != 0:
            logger.bind(channel='feishu', response_code=cls._response_code(body)).error(f'飞书卡片通知返回失败：{body}')
            return FeishuSendResult(False, error_message=str(body.get('msg') or body))

        logger.bind(channel='feishu').info('飞书卡片通知发送成功')
        return FeishuSendResult(True)

    @classmethod
    async def send_card_with_receipt(cls, card: dict[str, object]) -> FeishuSendResult:
        """发送飞书interactive卡片消息并返回发送凭据。"""
        if not FeishuNotifyConfig.feishu_notify_enabled:
            logger.debug('飞书通知未启用，跳过发送')
            return FeishuSendResult(False, error_message='飞书通知未启用')

        timeout = FeishuNotifyConfig.feishu_notify_timeout_seconds
        if FeishuNotifyConfig.feishu_notify_mode == 'app':
            return await cls._send_app_card(card, timeout)
        return await cls._send_webhook_card(card, timeout)

    @classmethod
    async def send_text_with_receipt(cls, text: str) -> FeishuSendResult:
        """发送文本消息并返回发送凭据。"""
        if not FeishuNotifyConfig.feishu_notify_enabled:
            logger.debug('飞书通知未启用，跳过发送')
            return FeishuSendResult(False, error_message='飞书通知未启用')

        timeout = FeishuNotifyConfig.feishu_notify_timeout_seconds
        if FeishuNotifyConfig.feishu_notify_mode == 'app':
            return await cls._send_app_text(text, timeout)
        return await cls._send_webhook_text(text, timeout)

    @classmethod
    async def send_text(cls, text: str) -> bool:
        """
        发送飞书文本消息。

        :param text: 消息正文
        :return: 飞书返回成功时为 True，未启用或发送失败时为 False
        """
        return (await cls.send_text_with_receipt(text)).ok

    @classmethod
    async def recall_message(cls, message_id: str) -> FeishuRecallResult:
        """撤回企业自建应用机器人发送的消息。"""
        if not FeishuNotifyConfig.feishu_notify_enabled:
            return FeishuRecallResult(False, message_id, '飞书通知未启用')
        if FeishuNotifyConfig.feishu_notify_mode != 'app':
            return FeishuRecallResult(False, message_id, '自定义机器人消息不支持撤回')
        if not FeishuNotifyConfig.feishu_app_id or not FeishuNotifyConfig.feishu_app_secret:
            return FeishuRecallResult(False, message_id, '飞书应用ID或应用密钥未配置')

        try:
            async with httpx.AsyncClient(timeout=FeishuNotifyConfig.feishu_notify_timeout_seconds) as client:
                token = await cls._get_app_token(client)
                response = await client.delete(
                    f'{MESSAGE_URL}/{message_id}',
                    headers={'Authorization': f'Bearer {token}'},
                )
                body = response.json()
                if response.status_code != httpx.codes.OK:
                    logger.bind(channel='feishu', message_id=message_id, status_code=response.status_code).error(
                        f'飞书消息撤回HTTP错误：{response.status_code} 响应体：{body}'
                    )
                    return FeishuRecallResult(False, message_id, f'飞书API返回HTTP {response.status_code}：{body}')
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.bind(channel='feishu', message_id=message_id).error(f'飞书消息撤回失败：{exc}')
            return FeishuRecallResult(False, message_id, str(exc))

        if cls._response_code(body) != 0:
            logger.bind(channel='feishu', message_id=message_id, response_code=cls._response_code(body)).error(
                f'飞书消息撤回返回失败：{body}'
            )
            return FeishuRecallResult(False, message_id, str(body.get('msg') or body))

        logger.bind(channel='feishu', message_id=message_id).info('飞书消息撤回成功')
        return FeishuRecallResult(True, message_id)

    @classmethod
    async def send_signal_with_receipt(cls, signal: FeishuSignal) -> FeishuSendResult:
        """推送单条实时交易信号并返回发送凭据。"""
        name = signal.name or ''
        price = f'{signal.price:.2f}' if signal.price is not None else '未知'
        time_suffix = f'\n时间：{signal.time}' if signal.time else ''
        text = (
            '【模拟交易信号】\n'
            f'股票：{signal.code} {name}\n'
            f'信号：{signal.signal}\n'
            f'现价：{price}\n'
            f'原因：{signal.reason or "无"}{time_suffix}'
        )
        return await cls.send_text_with_receipt(text)

    @classmethod
    async def send_signal(cls, signal: FeishuSignal) -> bool:
        """推送单条实时交易信号。"""
        return (await cls.send_signal_with_receipt(signal)).ok

    @staticmethod
    def _build_signal_summary_text(signals: list[FeishuSignal], signal_date: str) -> str:
        """构建收盘信号汇总文本。"""
        if not signals:
            return ''
        lines = [f'【模拟交易收盘信号】{signal_date}']
        for signal in signals:
            name = signal.name or ''
            price = f'{signal.price:.2f}' if signal.price is not None else '未知'
            lines.append(f'{signal.code} {name}：{signal.signal}，现价 {price}，原因 {signal.reason or "无"}')
        return '\n'.join(lines)

    @classmethod
    async def send_signal_summary_with_receipt(cls, signals: list[FeishuSignal], signal_date: str) -> FeishuSendResult:
        """推送收盘后的当日交易信号汇总并返回发送凭据。"""
        if not signals:
            return FeishuSendResult(False, error_message='没有可发送的信号')
        return await cls.send_text_with_receipt(cls._build_signal_summary_text(signals, signal_date))

    @classmethod
    async def send_signal_summary(cls, signals: list[FeishuSignal], signal_date: str) -> bool:
        """推送收盘后的当日交易信号汇总。"""
        return (await cls.send_signal_summary_with_receipt(signals, signal_date)).ok
