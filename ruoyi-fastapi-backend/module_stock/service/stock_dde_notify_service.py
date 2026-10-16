"""股票池 DDE 大单资金飞书通知服务。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import anyio

from config.database import DataSourceRegistry
from module_stock.dao.stock_pool_dao import StockPoolDao
from module_stock.service.stock_feishu_notification_service import FeishuNotificationService
from module_stock.service.stock_selector_service import StockSelectorService
from utils.log_util import logger
from utils.time_util import TimezoneUtil

_QUERY_TIMEOUT_SECONDS = 60
_TOP_DEFAULT = 30
_CHUNK_SIZE = 100
TRADING_DAY_MAX_WEEKDAY = 5


@dataclass(frozen=True)
class DDEStockRow:
    """通知中展示的单只股票指标。"""

    code: str
    name: str
    industry: str
    concepts: str
    price: float | None
    pct_change: float | None
    large_net: float | None
    market_cap: float | None
    strength: float | None
    institution_count: int | None
    trend_concepts: str
    big_institution_count: int | None
    linkage: str
    limit_up: bool = False


class StockDDENotifyService:
    """读取股票池、拉取同花顺问财DDE指标并推送飞书卡片。"""

    @classmethod
    async def send_pool_dde_notification(cls, pool_name: str = 'default', top_n: int = _TOP_DEFAULT) -> dict[str, Any]:
        """对指定股票池执行一次DDE大单资金通知。"""
        now = datetime.now(TimezoneUtil.get_app_timezone())
        if not cls._is_trading_day(now):
            return {
                'ok': True,
                'skipped': True,
                'message': '非交易日，跳过DDE通知',
                'pool_name': pool_name,
            }

        async with DataSourceRegistry.session() as db:
            pool_codes = await StockPoolDao.codes_by_pool(db, pool_name)
        if not pool_codes:
            return {
                'ok': False,
                'skipped': False,
                'message': f'股票池 {pool_name} 为空',
                'pool_name': pool_name,
            }

        codes = [code for code, _ in pool_codes]
        candidate_count = len(codes)
        raw_rows = await cls._fetch_market_rows(codes)
        rows = cls._normalize_rows(raw_rows, pool_codes)
        if not rows:
            return {
                'ok': False,
                'skipped': False,
                'message': f'股票池 {pool_name} 未获取到有效DDE数据',
                'pool_name': pool_name,
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
            'pool_name': pool_name,
            'candidate_count': len(rows),
            'inflow_count': len([row for row in tradable if (row.large_net or 0) > 0]),
            'outflow_count': len([row for row in tradable if (row.large_net or 0) < 0]),
            'sent_inflow': len(inflow),
            'sent_outflow': len(outflow),
            'message_id': receipt.message_id,
        }

    @classmethod
    async def _fetch_market_rows(cls, codes: list[str]) -> list[dict[str, Any]]:
        """分批调用问财接口并合并返回记录。"""
        results: list[dict[str, Any]] = []
        for offset in range(0, len(codes), _CHUNK_SIZE):
            chunk = codes[offset : offset + _CHUNK_SIZE]
            query = cls._build_query(chunk)
            try:
                raw_result = await anyio.to_thread.run_sync(
                    lambda q=query, size=len(chunk): StockSelectorService._load_selector_module().query_astock(
                        query=q,
                        page=1,
                        limit=size,
                        timeout=_QUERY_TIMEOUT_SECONDS,
                    )
                )
            except Exception:
                logger.bind(pool_codes=chunk).exception('问财DDE查询失败')
                continue
            if not isinstance(raw_result, dict):
                logger.bind(pool_codes=chunk).warning('问财DDE查询返回格式异常')
                continue
            datas = raw_result.get('datas') or []
            if isinstance(datas, list):
                results.extend(item for item in datas if isinstance(item, dict))
            else:
                logger.bind(pool_codes=chunk).warning('问财DDE查询缺少有效datas字段')
        return results

    @classmethod
    def _build_query(cls, codes: list[str]) -> str:
        """构造一次查询全量展示指标的问财问句。"""
        return (
            f"{' '.join(codes)} DDE大单净额 最新价 当日涨跌幅 总市值 流通市值 "
            '股东机构数量 行业 所属概念 走势概念 大机构 联动'
        )

    @classmethod
    def _normalize_rows(
        cls, raw_rows: list[dict[str, Any]], pool_codes: list[tuple[str, str | None]]
    ) -> list[DDEStockRow]:
        """清洗问财返回值，并按股票池代码顺序去重。"""
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
        code_value = str(raw.get('股票代码') or '')
        code = code_value.split('.', 1)[0].strip()
        if code.isdigit():
            code = code.zfill(6)
        if code not in pool_names:
            return None

        name = str(raw.get('股票简称') or pool_names.get(code) or '')
        price = cls._number(raw, ('最新价', '收盘价'))
        pct_change = cls._number(raw, ('涨跌幅',))
        large_net = cls._number(raw, ('大单净额',))
        market_cap = cls._market_cap(raw)
        strength = (large_net / market_cap * 100.0) if large_net is not None and market_cap else None
        institution_count = cls._optional_int(raw, ('机构股东家数', '股东机构数量', '机构家数'), exclude=('大机构',))
        big_institution_count = cls._optional_int(raw, ('大机构', '大股东机构数量', '大单机构'))
        concepts = cls._text(raw, ('所属概念', '概念'))
        return DDEStockRow(
            code=code,
            name=name,
            industry=cls._text(raw, ('行业',)) or '—',
            concepts=concepts or '—',
            price=price,
            pct_change=pct_change,
            large_net=large_net,
            market_cap=market_cap,
            strength=strength,
            institution_count=institution_count,
            trend_concepts=cls._text(raw, ('走势概念',)) or concepts or '—',
            big_institution_count=big_institution_count,
            linkage=cls._text(raw, ('联动',)) or '—',
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
            lines.append('每只股票一行展示完整指标')
            lines.extend(cls._format_row(index, row, period) for index, row in enumerate(inflow_rows, start=1))
        if outflow_rows:
            lines.append('')
            lines.append(f'**资金流出 Top{top_n}**')
            lines.append('每只股票一行展示完整指标')
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
            f"#{index} {row.name}（{row.code}）｜行业 {row.industry}｜概念 {row.concepts}｜时段 {period}｜"
            f'买入价 {cls._plain_number(row.price, 2)}｜涨跌幅 {cls._signed_number(row.pct_change, "%", 2)}｜'
            f'大单净额 {cls._signed_yi(row.large_net)}｜强度 {cls._signed_number(row.strength, "%", 2)}｜'
            f'市值 {cls._yi(row.market_cap)}｜机构 {cls._display_int(row.institution_count)}｜'
            f'走势概念 {row.trend_concepts}｜大机构 {cls._display_int(row.big_institution_count)}｜联动：{row.linkage}'
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

    @classmethod
    def _market_cap(cls, raw: dict[str, Any]) -> float | None:
        total = cls._number(raw, ('总市值',))
        if total is not None:
            return total
        return cls._number(raw, ('流通市值',))

    @classmethod
    def _number(cls, raw: dict[str, Any], prefixes: tuple[str, ...]) -> float | None:
        for prefix in prefixes:
            value = cls._select_value(raw, prefix)
            parsed = cls._to_float(value)
            if parsed is not None:
                return parsed
        return None

    @classmethod
    def _optional_int(
        cls, raw: dict[str, Any], prefixes: tuple[str, ...], exclude: tuple[str, ...] = ()
    ) -> int | None:
        for prefix in prefixes:
            value = cls._select_value(raw, prefix, exclude)
            parsed = cls._to_float(value)
            if parsed is not None:
                return int(parsed)
        return None

    @classmethod
    def _text(cls, raw: dict[str, Any], prefixes: tuple[str, ...]) -> str:
        for prefix in prefixes:
            value = cls._select_value(raw, prefix)
            text = cls._join_text(value)
            if text:
                return text
        return ''

    @classmethod
    def _select_value(cls, raw: dict[str, Any], prefix: str, exclude_prefixes: tuple[str, ...] = ()) -> Any:
        return next((raw[key] for key in raw if cls._field_matches(key, prefix, exclude_prefixes)), None)

    @staticmethod
    def _field_matches(key: str, prefix: str, exclude_prefixes: tuple[str, ...]) -> bool:
        if any(exclusion in key for exclusion in exclude_prefixes):
            return False
        return key == prefix or key.startswith(prefix)

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or isinstance(value, (list, dict)):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _join_text(value: Any) -> str:
        if value is None:
            return ''
        if isinstance(value, list):
            return '、'.join(str(item).strip() for item in value if str(item).strip())
        return str(value).strip()

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

    @staticmethod
    def _display_int(value: int | None) -> str:
        return '—' if value is None else str(value)
