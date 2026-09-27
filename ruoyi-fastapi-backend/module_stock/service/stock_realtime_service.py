"""收盘后实时行情采集与 Jk MA5 突破信号分析服务。"""

import math
from datetime import date as date_type, datetime, timedelta
from typing import Any

import anyio

from exceptions.exception import ServiceException
from utils.log_util import logger
from utils.time_util import TimezoneUtil

_DATE_COLUMN_CANDIDATES = ('date', 'datetime', 'trade_date')
_PRICE_COLUMN_CANDIDATES = ('price', 'close', 'last_price', 'now')
_PRE_CLOSE_COLUMN_CANDIDATES = ('pre_close', 'yesterday_close', 'preclose', 'last_close')


class StockRealtimeService:
    """
    股票实时行情采集与 MA5 突破信号服务

    每个交易日收盘后调用 QUANTAXIS 实时接口采集行情快照并写入 MongoDB（stock_realtime 集合），
    再结合历史日线计算 MA 均线，按 Jk 突破规则生成交易信号并以日志方式打印。
    """

    @classmethod
    async def collect_and_signal(
        cls,
        codes: list[str],
        package: str = 'tdx',
        ma_period: int = 5,
        breakout_ratio: float = 1.01,
    ) -> dict[str, Any]:
        """
        采集实时行情、写入MongoDB并分析MA突破信号（阻塞逻辑在线程池中执行）

        :param codes: 股票代码列表，如 ['000001']
        :param package: QUANTAXIS 实时行情数据源，默认 tdx
        :param ma_period: 均线周期，与 Jk 策略保持一致默认 5
        :param breakout_ratio: 突破阈值，收盘价高于 MA * breakout_ratio 视为买入信号
        :return: 采集与信号分析结果摘要
        """
        return await anyio.to_thread.run_sync(
            cls._collect_and_signal, list(codes), package, ma_period, breakout_ratio
        )

    @staticmethod
    def _collect_and_signal(
        codes: list[str], package: str, ma_period: int, breakout_ratio: float
    ) -> dict[str, Any]:
        try:
            import QUANTAXIS as QA  # noqa: PLC0415
            from pymongo import UpdateOne  # noqa: PLC0415
        except ImportError as exc:
            raise ServiceException(message='QUANTAXIS或pymongo未安装，无法采集股票实时行情') from exc

        if not codes:
            raise ServiceException(message='实时行情采集标的列表为空')

        try:
            frame = QA.QA_fetch_get_stock_realtime(package=package, code=codes)
        except Exception as exc:
            raise ServiceException(message=f'获取股票实时行情失败：{exc}') from exc

        if frame is None or frame.empty:
            message = f'未获取到股票{codes}的实时行情，可能是非交易日或行情源不可用'
            logger.bind(codes=codes, package=package).warning(message)
            return {'fetched_count': 0, 'saved_count': 0, 'signals': [], 'message': message}

        rows = frame.reset_index().to_dict(orient='records')
        collection = QA.DATABASE.stock_realtime
        collection.create_index([('code', 1), ('date', 1)], unique=True)

        fallback_date = datetime.now(TimezoneUtil.get_app_timezone()).date().isoformat()
        saved_count = 0
        signals: list[dict[str, Any]] = []
        for row in rows:
            record = StockRealtimeService._extract_realtime_record(row, fallback_date=fallback_date)
            if record is None:
                logger.bind(package=package).warning(f'实时行情记录缺少代码或最新价字段，已跳过：{row}')
                continue
            try:
                StockRealtimeService._upsert_realtime_record(collection, UpdateOne, record)
                saved_count += 1
            except Exception as exc:
                logger.bind(code=record['code']).error(f'股票{record["code"]}实时行情写入MongoDB失败：{exc}')
                continue
            signal = StockRealtimeService._analyze_signal(QA, collection, record, ma_period, breakout_ratio)
            if signal is not None:
                signals.append(signal)

        message = f'实时行情采集完成，共获取{len(rows)}条，写入{saved_count}条，产出MA{ma_period}信号{len(signals)}条'
        logger.bind(codes=codes, package=package).info(message)
        return {
            'fetched_count': len(rows),
            'saved_count': saved_count,
            'signals': signals,
            'message': message,
        }

    @staticmethod
    def _extract_realtime_record(row: dict[str, Any], fallback_date: str) -> dict[str, Any] | None:
        """
        从实时行情行记录中提取标准化的快照字段

        :param row: 实时行情单条记录
        :param fallback_date: 行情源缺少日期字段时使用的兜底日期
        :return: 标准化快照记录，缺少代码或最新价时返回 None
        """
        code = str(row.get('code') or '').strip()
        if not code:
            return None
        price = StockRealtimeService._clean_float(
            StockRealtimeService._first_present(row, _PRICE_COLUMN_CANDIDATES)
        )
        if price is None:
            return None

        record: dict[str, Any] = {
            'code': code,
            'date': StockRealtimeService._normalize_date(
                StockRealtimeService._first_present(row, _DATE_COLUMN_CANDIDATES), fallback_date=fallback_date
            ),
            'price': price,
            'update_time': datetime.now(TimezoneUtil.get_app_timezone()).isoformat(timespec='seconds'),
        }
        for field in ('open', 'high', 'low'):
            value = StockRealtimeService._clean_float(row.get(field))
            if value is not None:
                record[field] = value
        pre_close = StockRealtimeService._clean_float(
            StockRealtimeService._first_present(row, _PRE_CLOSE_COLUMN_CANDIDATES)
        )
        if pre_close is not None:
            record['pre_close'] = pre_close
        volume = StockRealtimeService._clean_float(StockRealtimeService._first_present(row, ('volume', 'vol')))
        if volume is not None:
            record['volume'] = volume
        amount = StockRealtimeService._clean_float(row.get('amount'))
        if amount is not None:
            record['amount'] = amount
        return record

    @staticmethod
    def _upsert_realtime_record(collection: Any, update_one: Any, record: dict[str, Any]) -> None:
        """
        按（code, date）将实时行情快照 upsert 到 stock_realtime 集合

        :param collection: MongoDB stock_realtime 集合
        :param update_one: pymongo UpdateOne 类
        :param record: 标准化快照记录
        :return: None
        """
        operations = [
            update_one(
                {'code': record['code'], 'date': record['date']},
                {'$set': record},
                upsert=True,
            )
        ]
        collection.bulk_write(operations, ordered=False)

    @staticmethod
    def _analyze_signal(
        qa_module: Any,
        collection: Any,
        record: dict[str, Any],
        ma_period: int,
        breakout_ratio: float,
    ) -> dict[str, Any] | None:
        """
        结合历史收盘价与实时收盘价计算均线并评估 Jk 突破信号

        :param qa_module: QUANTAXIS 模块（用于读取历史日线）
        :param collection: MongoDB stock_realtime 集合（历史快照兜底）
        :param record: 当日标准化快照记录
        :param ma_period: 均线周期
        :param breakout_ratio: 突破阈值
        :return: 信号记录，历史数据不足时返回 None
        """
        code = record['code']
        close = float(record['price'])
        history = StockRealtimeService._load_history_closes(
            qa_module, collection, code, before_date=record['date'], limit=ma_period - 1
        )
        if len(history) < ma_period - 1:
            logger.bind(code=code, date=record['date']).warning(
                f'股票{code}历史收盘价不足{ma_period - 1}个（当前{len(history)}个），跳过MA{ma_period}信号计算'
            )
            return None

        ma_value = round((sum(close for _, close in history) + close) / ma_period, 4)
        signal, reason = StockRealtimeService._evaluate_signal(close, ma_value, ma_period, breakout_ratio)
        payload = {
            'code': code,
            'date': record['date'],
            'signal': signal,
            'close': close,
            'ma_period': ma_period,
            'ma': ma_value,
            'reason': reason,
        }
        logger.bind(code=code, date=record['date'], signal=signal).info(
            f'📈 Jk策略交易信号: code={code}, date={record["date"]}, signal={signal}, '
            f'close={close:.2f}, MA{ma_period}={ma_value:.4f}, reason={reason}'
        )
        return payload

    @staticmethod
    def _evaluate_signal(close: float, ma_value: float, ma_period: int, breakout_ratio: float) -> tuple[str, str]:
        """
        按 Jk MA 突破规则评估信号：收盘价高于 MA 的 breakout_ratio 倍买入，低于 MA 卖出，其余持有观望

        :param close: 收盘价
        :param ma_value: 均线值
        :param ma_period: 均线周期
        :param breakout_ratio: 突破阈值
        :return: (信号方向, 触发原因)
        """
        if close > breakout_ratio * ma_value:
            return '买入', f'收盘价{close:.2f}高于MA{ma_period}({ma_value:.4f})超过{(breakout_ratio - 1) * 100:.0f}%'
        if close < ma_value:
            return '卖出', f'收盘价{close:.2f}低于MA{ma_period}({ma_value:.4f})'
        return '持有', f'收盘价{close:.2f}未突破MA{ma_period}({ma_value:.4f})阈值'

    @staticmethod
    def _load_history_closes(
        qa_module: Any, collection: Any, code: str, *, before_date: str, limit: int
    ) -> list[tuple[str, float]]:
        """
        加载指定日期之前最近的N个交易日收盘价

        stock_day 日线数据优先，stock_realtime 已采集的历史快照作为日线缺失时的兜底。

        :param qa_module: QUANTAXIS 模块（用于读取历史日线）
        :param collection: MongoDB stock_realtime 集合
        :param code: 股票代码
        :param before_date: 截止日期（不含），快照日期
        :param limit: 最多返回的收盘价个数
        :return: 按日期升序排列的 (日期, 收盘价) 列表
        """
        closes: dict[str, float] = {}
        try:
            cursor = (
                collection.find(
                    {'code': code, 'date': {'$lt': before_date, '$ne': None}},
                    {'_id': 0, 'date': 1, 'price': 1},
                )
                .sort('date', -1)
                .limit(limit)
            )
            for document in cursor:
                document_date = str(document.get('date') or '')[:10]
                price = StockRealtimeService._clean_float(document.get('price'))
                if document_date and price is not None:
                    closes[document_date] = price
        except Exception as exc:
            logger.bind(code=code).warning(f'股票{code}读取stock_realtime历史快照失败：{exc}')

        try:
            snapshot_date = date_type.fromisoformat(before_date)
            start_date = (snapshot_date - timedelta(days=60)).isoformat()
            end_date = (snapshot_date - timedelta(days=1)).isoformat()
            data = qa_module.QA_fetch_stock_day_adv(code, start_date, end_date)
            if data is not None and not data.data.empty:
                frame = data.data.reset_index()
                for _, row in frame.iterrows():
                    row_date = str(row['date'])[:10]
                    row_close = StockRealtimeService._clean_float(row['close'])
                    if row_date and row_close is not None:
                        closes[row_date] = row_close  # 日线数据优先，覆盖实时快照兜底值
        except Exception as exc:
            logger.bind(code=code).warning(f'股票{code}读取stock_day日线数据失败：{exc}')

        return sorted(closes.items())[-limit:]

    @staticmethod
    def _first_present(row: dict[str, Any], names: tuple[str, ...]) -> Any:
        """
        按候选字段名顺序取第一个存在的值

        :param row: 行情记录
        :param names: 候选字段名列表
        :return: 第一个存在的字段值，均不存在时返回 None
        """
        for name in names:
            if name in row:
                return row[name]
        return None

    @staticmethod
    def _clean_float(value: Any) -> float | None:
        """
        将任意值安全转换为有限浮点数

        :param value: 原始值
        :return: 浮点数值，无法转换或非有限值时返回 None
        """
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _normalize_date(value: Any, fallback_date: str) -> str:
        """
        将行情源日期值标准化为 ISO 日期字符串

        :param value: 原始日期值（datetime/date/字符串）
        :param fallback_date: 无法解析时使用的兜底日期
        :return: YYYY-MM-DD 格式日期字符串
        """
        if value is None:
            return fallback_date
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date_type):
            return value.isoformat()
        text = str(value).strip()
        if not text or text.lower() in {'nan', 'none', 'nat'}:
            return fallback_date
        try:
            return date_type.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return fallback_date
