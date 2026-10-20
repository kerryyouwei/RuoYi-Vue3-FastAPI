"""股票池 DDE 大单资金飞书通知服务。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from config.database import DataSourceRegistry
from module_stock.dao.stock_paper_dao import StockPaperDao
from module_stock.service.stock_feishu_notification_service import FeishuNotificationService
from utils.log_util import logger
from utils.time_util import TimezoneUtil

_EASTMONEY_ULIST_URL = 'https://push2.eastmoney.com/api/qt/ulist.np/get'
_EASTMONEY_UT = 'b2884a393a59ad64002292a3e90d46a5'
_EASTMONEY_FIELDS = 'f12,f14,f2,f3,f20,f21,f72'
_EASTMONEY_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
    ),
    'Referer': 'https://data.eastmoney.com/zjlx/detail.html',
}
_QUERY_TIMEOUT_SECONDS = 10.0
_TOP_DEFAULT = 30
_CHUNK_SIZE = 100
TRADING_DAY_MAX_WEEKDAY = 5


@dataclass(frozen=True)
class DDEStockRow:
    """通知中展示的单只股票指标。"""

    code: str
    name: str
    price: float | None
    pct_change: float | None
    large_net: float | None
    market_cap: float | None
    strength: float | None
    limit_up: bool = False


class StockDDENotifyService:
    """读取全账户标的池、拉取东方财富大单资金指标并推送飞书卡片。"""

    @classmethod
    async def send_pool_dde_notification(cls, pool_name: str = 'default', top_n: int = _TOP_DEFAULT, force: bool = False) -> dict[str, Any]:
        """对指定股票池执行一次DDE大单资金通知；force=True时绕过非交易日限制。"""
        now = datetime.now(TimezoneUtil.get_app_timezone())
        if not force and not cls._is_trading_day(now):
            return {
                'ok': True,
                'skipped': True,
                'message': '非交易日，跳过DDE通知',
                'pool_name': 'all_accounts',
            }

        async with DataSourceRegistry.session() as db:
            pool_codes = await StockPaperDao.list_universe_codes_all_accounts(db)
        if not pool_codes:
            return {
                'ok': False,
                'skipped': False,
                'message': '全账户标的池为空',
                'pool_name': 'all_accounts',
            }

        codes = [code for code, _ in pool_codes]
        candidate_count = len(codes)
        raw_rows = await cls._fetch_market_rows(codes)
        logger.info('DDE东财原始行数 candidate_count={} raw_row_count={}', candidate_count, len(raw_rows))
        rows = cls._normalize_rows(raw_rows, pool_codes)
        logger.info('DDE清洗后行数 normalized_row_count={}', len(rows))
        if not rows:
            return {
                'ok': False,
                'skipped': False,
                'message': '全账户标的池未获取到有效DDE数据',
                'pool_name': 'all_accounts',
                'candidate_count': candidate_count,
            }

        tradable = [row for row in rows if not row.limit_up]
        inflow = sorted(
            [row for row in tradable if (row.large_net or 0) > 0],
            key=lambda row: row.strength or -1e18,
            reverse=True,
        )[:top_n]
        outflow = sorted(
            [row for row in tradable if (row.large_net or 0) < 0],
            key=lambda row: row.strength or 1e18,
        )[:top_n]

        title = cls._build_title(now)
        card = cls._build_card(
            title=title,
            candidate_count=candidate_count,
            inflow_count=len([row for row in tradable if (row.large_net or 0) > 0]),
            outflow_count=len([row for row in tradable if (row.large_net or 0) < 0]),
            inflow_rows=inflow,
            outflow_rows=outflow,
            period=cls._trading_period(now),
            top_n=top_n,
        )
        receipt = await FeishuNotificationService.send_card_with_receipt(card)
        return {
            'ok': receipt.ok,
            'skipped': False,
            'message': receipt.error_message or 'DDE通知发送成功',
            'pool_name': 'all_accounts',
            'candidate_count': len(rows),
            'inflow_count': len([row for row in tradable if (row.large_net or 0) > 0]),
            'outflow_count': len([row for row in tradable if (row.large_net or 0) < 0]),
            'sent_inflow': len(inflow),
            'sent_outflow': len(outflow),
            'message_id': receipt.message_id,
        }

    @classmethod
    async def _fetch_market_rows(cls, codes: list[str]) -> list[dict[str, Any]]:
        """分批调用东方财富行情接口并合并返回记录。"""
        results: list[dict[str, Any]] = []
        for offset in range(0, len(codes), _CHUNK_SIZE):
            chunk = codes[offset : offset + _CHUNK_SIZE]
            params = {
                'secids': ','.join(cls._to_secid(code) for code in chunk),
                'fields': _EASTMONEY_FIELDS,
                'ut': _EASTMONEY_UT,
                'fltt': '2',
                'invt': '2',
                'pn': '1',
                'pz': str(len(chunk)),
                'po': '1',
                'np': '1',
                'fid': 'f3',
            }
            try:
                async with httpx.AsyncClient(
                    timeout=_QUERY_TIMEOUT_SECONDS,
                    headers=_EASTMONEY_HEADERS,
                ) as client:
                    response = await client.get(_EASTMONEY_ULIST_URL, params=params)
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError):
                logger.bind(pool_codes=chunk).exception('东方财富DDE查询失败')
                continue
            rows = cls._extract_response_rows(payload)
            if rows is None:
                logger.bind(pool_codes=chunk).warning('东方财富DDE查询返回格式异常')
                continue
            logger.bind(pool_codes=chunk).info('DDE东财返回行数 returned_row_count={}', len(rows))
            results.extend(rows)
        return results

    @staticmethod
    def _extract_response_rows(payload: Any) -> list[dict[str, Any]] | None:
        """提取东方财富 ulist.np/get 的 diff 数组。"""
        if not isinstance(payload, dict):
            return None
        data = payload.get('data')
        if not isinstance(data, dict):
            return None
        diff = data.get('diff')
        if isinstance(diff, list):
            return [item for item in diff if isinstance(item, dict)]
        if isinstance(diff, dict):
            return [item for item in diff.values() if isinstance(item, dict)]
        return None

    @staticmethod
    def _to_secid(code: str) -> str:
        """将6位股票代码转换为东方财富 secid。"""
        normalized = str(code).strip().zfill(6)
        return f'1.{normalized}' if normalized.startswith('6') else f'0.{normalized}'

    @classmethod
    def _normalize_rows(
        cls, raw_rows: list[dict[str, Any]], pool_codes: list[tuple[str, str | None]]
    ) -> list[DDEStockRow]:
        """清洗东财返回值，并按股票池代码顺序去重。"""
        by_code: dict[str, DDEStockRow] = {}
        pool_names = dict(pool_codes)
        for raw in raw_rows:
            row = cls._normalize_row(raw, pool_names)
            if row is None or row.code in by_code:
                continue
            by_code[row.code] = row
        return [by_code[code] for code in pool_names if code in by_code]

    @classmethod
    def _normalize_row(cls, raw: dict[str, Any], pool_names: dict[str, str | None]) -> DDEStockRow | None:
        code_value = str(raw.get('f12') or '')
        code = code_value.split('.', 1)[0].strip()
        if code.isdigit():
            code = code.zfill(6)
        if code not in pool_names:
            return None

        name = str(raw.get('f14') or pool_names.get(code) or '')
        price = cls._to_float(raw.get('f2'))
        pct_change = cls._to_float(raw.get('f3'))
        large_net = cls._to_float(raw.get('f72'))
        market_cap = cls._to_float(raw.get('f20')) or cls._to_float(raw.get('f21'))
        strength = (large_net / market_cap * 100.0) if large_net is not None and market_cap else None
        return DDEStockRow(
            code=code,
            name=name,
            price=price,
            pct_change=pct_change,
            large_net=large_net,
            market_cap=market_cap,
            strength=strength,
            limit_up=cls._is_limit_up(code, name, pct_change),
        )

    @classmethod
    def _build_title(cls, now: datetime) -> str:
        return f'{cls._trading_period(now)}｜DDE 大单资金｜{now.strftime("%Y%m%d")}'

    @classmethod
    def _build_card(
        cls,
        *,
        title: str,
        candidate_count: int,
        inflow_count: int,
        outflow_count: int,
        inflow_rows: list[DDEStockRow],
        outflow_rows: list[DDEStockRow],
        period: str,
        top_n: int = _TOP_DEFAULT,
    ) -> dict[str, Any]:
        """构造飞书interactive卡片，正数红色、负数绿色。"""
        lines = [
            f'**盘面速览　候选 {candidate_count} 只｜流入 {inflow_count} 只｜流出 {outflow_count} 只**',
            '按大单净额 / 市值排序，涨停股不纳入可交易列表',
        ]
        if inflow_rows:
            lines.append('')
            lines.append(f'**资金流入 Top{top_n}**')
            lines.extend(cls._format_row(index, row, period) for index, row in enumerate(inflow_rows, start=1))
        if outflow_rows:
            lines.append('')
            lines.append(f'**资金流出 Top{top_n}**')
            lines.extend(cls._format_row(index, row, period) for index, row in enumerate(outflow_rows, start=1))
        return {
            'config': {'wide_screen_mode': True},
            'header': {
                'title': {'tag': 'plain_text', 'content': title},
                'template': 'blue',
            },
            'elements': [{'tag': 'div', 'text': {'tag': 'lark_md', 'content': '\n'.join(lines)}}],
        }

    @classmethod
    def _format_row(cls, index: int, row: DDEStockRow, period: str) -> str:
        return (
            f"#{index} {row.name}（{row.code}）｜时段 {period}｜"
            f'买入价 {cls._plain_number(row.price, 2)}｜涨跌幅 {cls._signed_number(row.pct_change, "%", 2)}｜'
            f'大单净额 {cls._signed_yi(row.large_net)}｜强度 {cls._signed_number(row.strength, "%", 2)}｜'
            f'市值 {cls._yi(row.market_cap)}'
        )

    @classmethod
    def _is_trading_day(cls, now: datetime) -> bool:
        """项目现有定时任务同样以周一至周五兜底，节假日由行情无数据自然跳过。"""
        return now.weekday() < TRADING_DAY_MAX_WEEKDAY

    @classmethod
    def _trading_period(cls, now: datetime) -> str:
        minute_of_day = now.hour * 60 + now.minute
        if 9 * 60 <= minute_of_day < 10 * 60:
            return '开盘'
        if 10 * 60 <= minute_of_day < 12 * 60:
            return '早盘'
        if 13 * 60 <= minute_of_day < 14 * 60 + 30:
            return '午盘'
        if 14 * 60 + 30 <= minute_of_day < 15 * 60:
            return '尾盘'
        return '盘后'

    @classmethod
    def _is_limit_up(cls, code: str, name: str, pct_change: float | None) -> bool:
        """用涨跌幅阈值识别涨停，避免额外逐票拉取涨跌停价。"""
        if pct_change is None:
            return False
        if code.startswith(('30', '68')):
            threshold = 19.9
        elif code.startswith(('43', '83', '87', '92')):
            threshold = 29.9
        elif 'ST' in name.upper():
            threshold = 4.9
        else:
            threshold = 9.9
        return pct_change >= threshold

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """容错解析东方财富数值字段。"""
        if value is None or isinstance(value, (list, dict)):
            return None
        if isinstance(value, str):
            text = value.strip().replace(',', '').replace('%', '').replace(' ', '')
            if text in {'', '--', '-', '—'}:
                return None
            try:
                return float(text)
            except (TypeError, ValueError):
                return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _signed_number(value: float | None, suffix: str, digits: int) -> str:
        if value is None:
            return '—'
        color = 'red' if value > 0 else 'green' if value < 0 else 'grey'
        sign = '+' if value > 0 else ''
        return f"<font color='{color}'>{sign}{value:.{digits}f}{suffix}</font>"

    @classmethod
    def _signed_yi(cls, value: float | None) -> str:
        if value is None:
            return '—'
        yi_value = value / 100_000_000
        color = 'red' if yi_value > 0 else 'green' if yi_value < 0 else 'grey'
        sign = '+' if yi_value > 0 else ''
        return f"<font color='{color}'>{sign}{yi_value:.2f}亿</font>"

    @staticmethod
    def _plain_number(value: float | None, digits: int) -> str:
        return '—' if value is None else f'{value:.{digits}f}'

    @staticmethod
    def _yi(value: float | None) -> str:
        return '—' if value is None else f'{value / 100_000_000:.0f}亿'
