"""Baostock + akshare 数据拉取服务，用于多因子选股（带本地缓存层）。

缓存策略:
- K线: 增量更新，只拉上次缓存日期之后的数据
- 财务: 按季度缓存，已存在的季度不再重复拉取
- 行业: 缓存7天后自动刷新
- 北向资金: 每次计算实时拉取（数据时效性要求高），失败降级
"""

import asyncio
import time
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from module_stock.dao.multi_factor_cache_dao import MultiFactorCacheDao
from module_stock.entity.do.multi_factor_do import (
    MultiFactorFinancialCache,
    MultiFactorIndustryCache,
    MultiFactorKlineCache,
)
from utils.log_util import logger

_LOCK = asyncio.Lock()
_LOGGED_IN = False

# 行业缓存有效期（天）
_INDUSTRY_CACHE_TTL_DAYS = 7
# K线最少保留天数
_KLINE_MIN_DAYS = 120


async def _ensure_login() -> None:
    global _LOGGED_IN
    async with _LOCK:
        if _LOGGED_IN:
            return
        import baostock as bs
        result = await asyncio.to_thread(bs.login)
        if result.error_code != '0':
            raise RuntimeError(f'Baostock登录失败: {result.error_msg}')
        _LOGGED_IN = True


async def _logout() -> None:
    global _LOGGED_IN
    async with _LOCK:
        if _LOGGED_IN:
            import baostock as bs
            await asyncio.to_thread(bs.logout)
            _LOGGED_IN = False


def _last_trading_day() -> str:
    d = datetime.now()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime('%Y-%m-%d')


def _recent_trading_days(count: int = 5) -> list[str]:
    days = []
    d = datetime.now()
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d.strftime('%Y-%m-%d'))
        d -= timedelta(days=1)
    return days


def _bs_query_to_df(query_result: Any) -> pd.DataFrame:
    """将 Baostock ResultData 转为 DataFrame。"""
    rows = []
    while query_result.error_code == '0' and query_result.next():
        rows.append(query_result.get_row_data())
    if not rows:
        return pd.DataFrame(columns=query_result.fields)
    return pd.DataFrame(rows, columns=query_result.fields)


class BaostockDataService:
    """Baostock 数据拉取（带DB缓存层）。"""

    _stock_list_cache: pd.DataFrame | None = None
    _cache_time: float = 0
    _CACHE_TTL = 3600

    # ============ 股票列表（内存缓存即可，无需DB持久化） ============

    @classmethod
    async def fetch_stock_list(cls) -> pd.DataFrame:
        now = time.time()
        if cls._stock_list_cache is not None and now - cls._cache_time < cls._CACHE_TTL:
            return cls._stock_list_cache.copy()

        await _ensure_login()
        import baostock as bs

        def _query() -> pd.DataFrame:
            for day in _recent_trading_days(3):
                rs = bs.query_all_stock(day=day)
                tmp = _bs_query_to_df(rs)
                if not tmp.empty:
                    return tmp
            return pd.DataFrame()

        df = await asyncio.to_thread(_query)
        if df.empty:
            raise RuntimeError('Baostock股票列表为空')

        mask = (
            df['code'].str.startswith('sh.6')
            | df['code'].str.startswith('sz.0')
            | df['code'].str.startswith('sz.3')
        )
        df = df[mask].copy()
        df['pure_code'] = df['code'].str.split('.').str[1]

        cls._stock_list_cache = df
        cls._cache_time = now
        logger.info(f'Baostock股票列表获取成功，共{len(df)}只A股')
        return df.copy()

    # ============ K线数据（带DB增量缓存） ============

    @classmethod
    async def fetch_kline_cached(
        cls, db: AsyncSession, codes: list[str], days: int = _KLINE_MIN_DAYS
    ) -> pd.DataFrame:
        """获取K线数据，优先从DB缓存读取，不足部分从Baostock增量拉取并写入DB。

        返回 DataFrame 列: code, pure_code, date, close, peTTM, pbMRQ, turn, volume, amount
        """
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        all_records: list[MultiFactorKlineCache] = []
        codes_need_fetch: list[tuple[str, str]] = []  # (bs_code, from_date)

        # 1. 查询每只股票的缓存截止日期
        cached_rows = await db.execute(
            select(
                MultiFactorKlineCache.code,
                func.max(MultiFactorKlineCache.trade_date).label('last_date'),
            )
            .where(MultiFactorKlineCache.pure_code.in_([c.split('.')[1] for c in codes]))
            .group_by(MultiFactorKlineCache.code)
        )
        cache_map: dict[str, date] = {row.code: row.last_date for row in cached_rows}

        # 2. 决定哪些需要增量拉取
        for bs_code in codes:
            last_cached = cache_map.get(bs_code)
            if last_cached and last_cached >= date.fromisoformat(_last_trading_day()):
                # 缓存已是最新，直接用
                continue
            from_date = last_cached + timedelta(days=1) if last_cached else start_date
            from_str = from_date.strftime('%Y-%m-%d')
            if from_str <= _last_trading_day():
                codes_need_fetch.append((bs_code, from_str))

        # 3. 从DB读取已有缓存
        pure_codes = [c.split('.')[1] for c in codes]
        if cache_map:
            db_records = await MultiFactorCacheDao.load_kline_cache(db, pure_codes)
            all_records.extend(db_records)
            logger.info(f'K线缓存命中: {len(db_records)} 条')

        # 4. 增量拉取缺失部分
        if codes_need_fetch:
            logger.info(f'K线需要增量拉取: {len(codes_need_fetch)} 只股票')
            new_records = await cls._fetch_kline_incremental(codes_need_fetch, days)
            all_records.extend(new_records)
            # 写入DB
            if new_records:
                written = await MultiFactorCacheDao.upsert_kline(db, new_records)
                logger.info(f'K线缓存写入: {written} 条')

        # 5. 转为 DataFrame
        return cls._kline_records_to_df(all_records)

    @classmethod
    async def _fetch_kline_incremental(
        cls, codes_with_dates: list[tuple[str, str]], days: int
    ) -> list[MultiFactorKlineCache]:
        """从Baostock增量拉取K线数据并转为缓存记录。"""
        await _ensure_login()
        import baostock as bs

        end_date = datetime.now().strftime('%Y-%m-%d')
        all_records: list[MultiFactorKlineCache] = []

        def _query_one(code: str, from_date: str) -> pd.DataFrame:
            rs = bs.query_history_k_data_plus(
                code,
                'date,code,close,peTTM,pbMRQ,turn,volume,amount',
                start_date=from_date,
                end_date=end_date,
                frequency='d',
                adjustflag='2',
            )
            return _bs_query_to_df(rs)

        for i, (bs_code, from_date) in enumerate(codes_with_dates):
            try:
                df = await asyncio.to_thread(_query_one, bs_code, from_date)
                for _, row in df.iterrows():
                    if not row.get('date'):
                        continue
                    all_records.append(MultiFactorKlineCache(
                        code=bs_code,
                        pure_code=bs_code.split('.')[1],
                        trade_date=date.fromisoformat(str(row['date'])[:10]),
                        close=_to_decimal(row.get('close')),
                        pe_ttm=_to_decimal(row.get('peTTM')),
                        pb_mrq=_to_decimal(row.get('pbMRQ')),
                        turn=_to_decimal(row.get('turn')),
                        volume=_to_decimal(row.get('volume')),
                        amount=_to_decimal(row.get('amount')),
                    ))
            except Exception as exc:
                logger.warning(f'K线增量拉取失败 code={bs_code}: {exc}')
            if i % 50 == 0 and i > 0:
                logger.info(f'K线增量拉取进度: {i}/{len(codes_with_dates)}')
            await asyncio.sleep(0.05)

        return all_records

    @staticmethod
    def _kline_records_to_df(records: list[MultiFactorKlineCache]) -> pd.DataFrame:
        """将缓存记录转为计算用的 DataFrame。"""
        if not records:
            return pd.DataFrame(columns=['code', 'pure_code', 'date', 'close', 'peTTM', 'pbMRQ', 'turn', 'volume', 'amount'])
        data = []
        for r in records:
            data.append({
                'code': r.code,
                'pure_code': r.pure_code,
                'date': str(r.trade_date),
                'close': float(r.close) if r.close is not None else None,
                'peTTM': float(r.pe_ttm) if r.pe_ttm is not None else None,
                'pbMRQ': float(r.pb_mrq) if r.pb_mrq is not None else None,
                'turn': float(r.turn) if r.turn is not None else None,
                'volume': float(r.volume) if r.volume is not None else None,
                'amount': float(r.amount) if r.amount is not None else None,
            })
        return pd.DataFrame(data)

    # ============ 财务数据（带DB缓存） ============

    @classmethod
    async def fetch_financial_cached(cls, db: AsyncSession) -> pd.DataFrame:
        """获取财务数据，优先从DB缓存读取，不足部分从Baostock拉取。"""
        now = datetime.now()
        year, quarter = now.year, (now.month - 1) // 3 + 1

        # 确定要获取的季度（可能需要回退）
        target_quarters = cls._resolve_quarters(year, quarter)

        # 检查DB缓存中已有哪些季度
        cached = await db.execute(
            select(MultiFactorFinancialCache.year, MultiFactorFinancialCache.quarter)
            .distinct()
        )
        cached_quarters = {(row.year, row.quarter) for row in cached}

        # 找出缺失的季度
        missing = [(y, q) for y, q in target_quarters if (y, q) not in cached_quarters]

        # 从DB读取缓存
        db_records = await MultiFactorCacheDao.load_financial_cache(db)
        all_records = list(db_records)
        logger.info(f'财务缓存命中: {len(db_records)} 条, 覆盖季度: {sorted(cached_quarters)}')

        # 拉取缺失季度
        if missing:
            logger.info(f'财务数据需要拉取: {missing}')
            new_records = await cls._fetch_financial_by_quarters(missing)
            all_records.extend(new_records)
            if new_records:
                written = await MultiFactorCacheDao.upsert_financial(db, new_records)
                logger.info(f'财务缓存写入: {written} 条')

        return cls._financial_records_to_df(all_records)

    @staticmethod
    def _resolve_quarters(year: int, quarter: int) -> list[tuple[int, int]]:
        """确定需要获取的季度列表（当前季度 + 回退到有数据的季度，最多4个）。"""
        result = []
        for _ in range(4):
            if quarter <= 0:
                year -= 1
                quarter = 4
            result.append((year, quarter))
            quarter -= 1
        return result

    @classmethod
    async def _fetch_financial_by_quarters(cls, quarters: list[tuple[int, int]]) -> list[MultiFactorFinancialCache]:
        """从Baostock拉取指定季度的财务数据。"""
        await _ensure_login()
        import baostock as bs
        all_records: list[MultiFactorFinancialCache] = []

        for y, q in quarters:
            def _query_profit(yy=y, qq=q):
                rs = bs.query_profit_data(code='', year=yy, quarter=qq)
                return _bs_query_to_df(rs)

            def _query_growth(yy=y, qq=q):
                rs = bs.query_growth_data(code='', year=yy, quarter=qq)
                return _bs_query_to_df(rs)

            try:
                profit_df = await asyncio.to_thread(_query_profit)
                growth_df = await asyncio.to_thread(_query_growth)
            except Exception as exc:
                logger.warning(f'Baostock财务拉取失败 {y}Q{q}: {exc}')
                continue

            if profit_df.empty and growth_df.empty:
                continue

            # 合并 profit 和 growth
            if not profit_df.empty and not growth_df.empty:
                merge_cols = ['code', 'pubDate', 'statDate']
                merged = pd.merge(profit_df, growth_df, on=merge_cols, how='outer', suffixes=('', '_g'))
            elif not profit_df.empty:
                merged = profit_df
            else:
                merged = growth_df

            for _, row in merged.iterrows():
                bs_code = row.get('code', '')
                if not bs_code:
                    continue
                all_records.append(MultiFactorFinancialCache(
                    code=bs_code,
                    pure_code=bs_code.split('.')[1] if '.' in str(bs_code) else str(bs_code),
                    year=y,
                    quarter=q,
                    roe_avg=_to_decimal(row.get('roeAvg')),
                    np_margin=_to_decimal(row.get('npMargin')),
                    yoy_ni=_to_decimal(row.get('YOYNI')),
                    yoy_equity=_to_decimal(row.get('YOYEquity')),
                    stat_date=_to_date(row.get('statDate')),
                    pub_date=_to_date(row.get('pubDate')),
                ))

        return all_records

    @staticmethod
    def _financial_records_to_df(records: list[MultiFactorFinancialCache]) -> pd.DataFrame:
        if not records:
            return pd.DataFrame(columns=['code', 'pure_code', 'roeAvg', 'npMargin', 'YOYNI', 'YOYEquity'])
        data = []
        for r in records:
            data.append({
                'code': r.code,
                'pure_code': r.pure_code,
                'roeAvg': float(r.roe_avg) if r.roe_avg is not None else None,
                'npMargin': float(r.np_margin) if r.np_margin is not None else None,
                'YOYNI': float(r.yoy_ni) if r.yoy_ni is not None else None,
                'YOYEquity': float(r.yoy_equity) if r.yoy_equity is not None else None,
            })
        return pd.DataFrame(data)

    # ============ 行业分类（带DB缓存，7天刷新） ============

    @classmethod
    async def fetch_industry_cached(cls, db: AsyncSession) -> pd.DataFrame:
        """获取行业分类，DB缓存7天。"""
        last_update = await MultiFactorCacheDao.get_industry_last_update(db)
        if last_update and (date.today() - last_update).days < _INDUSTRY_CACHE_TTL_DAYS:
            records = await MultiFactorCacheDao.load_industry_cache(db)
            if records:
                logger.info(f'行业缓存命中: {len(records)} 条, 更新于 {last_update}')
                return cls._industry_records_to_df(records)

        # 缓存过期或为空，从Baostock拉取
        fresh_df = await cls.fetch_industry_raw()
        if fresh_df.empty:
            # 拉取失败，尝试用旧缓存
            records = await MultiFactorCacheDao.load_industry_cache(db)
            if records:
                logger.warning('行业拉取失败，使用旧缓存')
                return cls._industry_records_to_df(records)
            return fresh_df

        # 清除旧缓存，写入新缓存
        await MultiFactorCacheDao.clear_industry_cache(db)
        new_records = []
        for _, row in fresh_df.iterrows():
            bs_code = row.get('code', '')
            pure = str(bs_code).split('.')[1] if '.' in str(bs_code) else str(bs_code)
            new_records.append(MultiFactorIndustryCache(
                pure_code=pure,
                code=str(bs_code),
                industry_name=str(row.get('industry', row.get('industryName', '')) or ''),
                industry_type=str(row.get('industryType', '') or ''),
                update_date=date.today(),
            ))
        written = await MultiFactorCacheDao.upsert_industry(db, new_records)
        logger.info(f'行业缓存写入: {written} 条')
        return fresh_df

    @classmethod
    async def fetch_industry_raw(cls) -> pd.DataFrame:
        """直接从Baostock拉取行业分类（无缓存）。"""
        await _ensure_login()
        import baostock as bs

        def _query() -> pd.DataFrame:
            rs = bs.query_stock_industry()
            return _bs_query_to_df(rs)

        df = await asyncio.to_thread(_query)
        if not df.empty:
            df['pure_code'] = df['code'].str.split('.').str[1]
        logger.info(f'Baostock行业分类获取成功，共{len(df)}条')
        return df

    @staticmethod
    def _industry_records_to_df(records: list[MultiFactorIndustryCache]) -> pd.DataFrame:
        if not records:
            return pd.DataFrame(columns=['code', 'pure_code', 'industry', 'industryType'])
        data = []
        for r in records:
            data.append({
                'code': r.code,
                'pure_code': r.pure_code,
                'industry': r.industry_name,
                'industryType': r.industry_type,
            })
        return pd.DataFrame(data)

    # ============ 北向资金（实时拉取，不缓存，失败降级） ============

    @classmethod
    async def fetch_northbound(cls) -> pd.DataFrame:
        """获取北向持仓数据（akshare/eastmoney）。

        尝试多个指标：今日新增 > 3日新增 > 季度新增，取第一个有数据的。
        失败返回空DataFrame，不阻塞整体计算。
        """
        try:
            import akshare as ak

            for indicator in ('今日新增', '3日新增', '季度新增'):
                try:
                    def _query(ind=indicator):
                        return ak.stock_hsgt_hold_stock_em(market='北向', indicator=ind)

                    df = await asyncio.to_thread(_query)
                    if df is not None and not df.empty:
                        logger.info(
                            f'akshare北向持仓数据获取成功, '
                            f'indicator={indicator}, 共{len(df)}条'
                        )
                        return df
                except Exception as inner_exc:
                    logger.debug(f'akshare北向持仓 indicator={indicator} 失败: {inner_exc}')
                    continue

            logger.warning('akshare北向持仓所有指标均无数据，将降级为中性分')
            return pd.DataFrame()
        except Exception as exc:
            logger.warning(f'akshare北向持仓拉取失败（将降级为中性分）: {exc}')
            return pd.DataFrame()

    # ============ 保留旧接口名（向后兼容） ============

    @classmethod
    async def fetch_kline_batch(cls, codes: list[str], days: int = 120) -> pd.DataFrame:
        """旧接口，不带缓存。保留供测试用。"""
        await _ensure_login()
        import baostock as bs
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')
        all_frames: list[pd.DataFrame] = []

        def _query_one(code: str) -> pd.DataFrame:
            rs = bs.query_history_k_data_plus(
                code, 'date,code,close,peTTM,pbMRQ,turn,volume,amount',
                start_date=start_date, end_date=end_date, frequency='d', adjustflag='2',
            )
            return _bs_query_to_df(rs)

        for code in codes:
            try:
                df = await asyncio.to_thread(_query_one, code)
                if not df.empty:
                    all_frames.append(df)
            except Exception:
                pass
            await asyncio.sleep(0.05)

        if not all_frames:
            return pd.DataFrame()
        result = pd.concat(all_frames, ignore_index=True)
        for col in ('close', 'peTTM', 'pbMRQ', 'turn', 'volume', 'amount'):
            if col in result.columns:
                result[col] = pd.to_numeric(result[col], errors='coerce')
        return result

    @classmethod
    async def fetch_financial_data(cls) -> pd.DataFrame:
        """旧接口，不带缓存。保留供测试用。"""
        df = await cls._fetch_financial_by_quarters(cls._resolve_quarters(datetime.now().year, (datetime.now().month - 1) // 3 + 1))
        return cls._financial_records_to_df(df)

    @classmethod
    async def fetch_industry(cls) -> pd.DataFrame:
        """旧接口，不带缓存。"""
        return await cls.fetch_industry_raw()

    @classmethod
    async def close(cls) -> None:
        await _logout()


def _to_decimal(value) -> float | None:
    """安全转为 float（用于 Numeric 列）。"""
    if value is None or value == '':
        return None
    try:
        result = float(value)
        if pd.isna(result) or pd.isinf(result):
            return None
        return result
    except (ValueError, TypeError):
        return None


def _to_date(value) -> date | None:
    """安全转为 date。"""
    if value is None or value == '' or str(value).strip() == '':
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (ValueError, TypeError):
        return None
