"""多因子选股服务：因子计算、打分、入库。"""

import asyncio
import time
import uuid
from datetime import date, datetime

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from config.database import DataSourceRegistry
from exceptions.exception import ServiceException
from module_stock.dao.multi_factor_dao import MultiFactorDao
from module_stock.dao.stock_pool_dao import StockPoolDao
from module_stock.entity.do.multi_factor_do import MultiFactorResult
from module_stock.entity.vo.multi_factor_vo import (
    MultiFactorBatchInfoModel,
    MultiFactorCalcResultModel,
    MultiFactorFactorWeightModel,
    MultiFactorPoolAddRequestModel,
    MultiFactorPoolAddResultModel,
    MultiFactorResultQueryModel,
    MultiFactorResultModel,
    MultiFactorWeightSaveRequestModel,
    MultiFactorWeightSettingsModel,
)
from module_stock.service.baostock_data_service import BaostockDataService
from utils.log_util import logger

# 因子中文标签映射
FACTOR_LABELS = {
    'roe': 'ROE',
    'peg': 'PEG',
    'profit_growth': '利润增长',
    'volume': '成交量',
    'macd': 'MACD',
    'northbound': '北向持仓变化',
    'industry': '行业景气',
}

# 默认权重（百分比），与 multi_factor_config 初始化一致
_DEFAULT_WEIGHTS = {
    'roe': 22.5,
    'peg': 15.0,
    'profit_growth': 17.5,
    'volume': 10.0,
    'macd': 10.0,
    'northbound': 10.0,
    'industry': 15.0,
}


def _percentile_score(series: pd.Series, reverse: bool = False) -> pd.Series:
    """0-100百分位打分。reverse=True时反序（越低越好）。"""
    valid = series.dropna()
    if len(valid) < 2:
        return pd.Series(50.0, index=series.index)
    ranks = valid.rank(pct=True, method='average')
    if reverse:
        ranks = 1 - ranks
    result = (ranks * 100).round(2)
    return result.reindex(series.index)


def _compute_macd(close_series: pd.Series) -> dict:
    """计算MACD指标，返回信号和得分。"""
    if len(close_series) < 35:
        return {'signal': '数据不足', 'score': 50.0}
    close = close_series.astype(float)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = 2 * (dif - dea)

    latest_dif = dif.iloc[-1]
    latest_dea = dea.iloc[-1]
    prev_dif = dif.iloc[-2]
    prev_dea = dea.iloc[-2]
    latest_hist = hist.iloc[-1]

    if prev_dif <= prev_dea and latest_dif > latest_dea:
        signal = '金叉'
        score = 100.0 if latest_dif > 0 else 80.0
    elif prev_dif >= prev_dea and latest_dif < latest_dea:
        signal = '死叉'
        score = 10.0
    elif latest_dif > latest_dea:
        signal = '多头'
        score = 80.0 if latest_dif > 0 else 60.0
    else:
        signal = '空头'
        score = 30.0 if latest_hist < 0 else 40.0
    return {'signal': signal, 'score': score}


class MultiFactorService:
    """多因子选股主服务。"""

    # 计算状态缓存（内存）
    _calc_status: dict[str, dict] = {}
    _calc_running: bool = False
    _calc_task: asyncio.Task | None = None

    @classmethod
    @property
    def is_calculating(cls) -> bool:
        """是否正在后台计算。"""
        return cls._calc_running

    @classmethod
    def start_background_calculation(cls) -> bool:
        """启动后台计算任务，返回是否成功启动。"""
        if cls._calc_running:
            return False
        cls._calc_running = True
        cls._calc_task = asyncio.create_task(cls._calculate_in_background())
        return True

    @classmethod
    async def cancel_background_calculation(cls) -> None:
        """取消后台计算并等待任务退出，避免应用关闭时破坏数据库会话。"""
        task = cls._calc_task
        if task is None or task.done():
            cls._calc_running = False
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        cls._calc_running = False
        cls._calc_task = None

    @classmethod
    async def _calculate_in_background(cls) -> None:
        """使用独立数据库会话执行计算，不受HTTP请求超时/断开影响。"""
        try:
            async with DataSourceRegistry.session() as db:
                result = await cls.calculate(db)
            cls._calc_status = {
                'status': 'completed',
                'batch_id': result.batch_id,
                'total_count': result.total_count,
                'selected_count': result.selected_count,
            }
        except asyncio.CancelledError:
            cls._calc_status = {'status': 'cancelled'}
            raise
        except Exception as exc:
            cls._calc_status = {'status': 'failed', 'message': str(exc)}
            logger.exception('多因子后台计算失败')
        finally:
            cls._calc_running = False
            cls._calc_task = None

    @classmethod
    async def calculate(cls, db: AsyncSession) -> MultiFactorCalcResultModel:
        """主入口：拉取数据→计算因子→打分→入库。"""
        start_time = time.time()
        batch_id = uuid.uuid4().hex[:32]
        degraded_factors: list[str] = []

        # 0. 读取权重和入选阈值快照，避免长任务执行期间配置变化影响同一批次。
        weights = await cls._get_effective_weights(db)
        selected_threshold = await MultiFactorDao.get_selected_threshold(db)

        # 1. 获取股票列表
        stock_list = await BaostockDataService.fetch_stock_list()
        if stock_list.empty:
            raise ServiceException(message='Baostock股票列表为空')

        # 2. 获取财务数据（ROE/利润增长）
        financial_df = await BaostockDataService.fetch_financial_cached(db)

        # 3. 获取行业分类
        industry_df = await BaostockDataService.fetch_industry_cached(db)

        # 4. 获取北向资金（可选）
        northbound_df = await BaostockDataService.fetch_northbound()
        if northbound_df.empty:
            degraded_factors.append('northbound')

        # 5. 拉取K线数据（全市场，用于换手率/MACD/PE）
        codes_bs = stock_list['code'].tolist()
        kline_df = await BaostockDataService.fetch_kline_cached(db, codes_bs, days=120)

        # 6. 构建基础DataFrame
        df = stock_list[['pure_code', 'code_name', 'code']].copy()
        df = df.rename(columns={'code_name': 'name', 'code': 'bs_code'})
        df = df.set_index('pure_code')

        # 7. 合并财务数据
        if not financial_df.empty:
            fin_sub = financial_df.set_index('pure_code')
            for col, target in [('roeAvg', 'roe_value'), ('YOYNI', 'profit_growth_value')]:
                if col in fin_sub.columns:
                    df[target] = fin_sub[col]

        # 8. 合并行业数据
        if not industry_df.empty:
            ind_sub = industry_df.set_index('pure_code')
            if 'industry' in ind_sub.columns:
                df['industry_name'] = ind_sub['industry']
            elif 'industryName' in ind_sub.columns:
                df['industry_name'] = ind_sub['industryName']

        # 9. 从K线提取最新交易日数据（换手率/PE）
        if not kline_df.empty:
            kline_df['pure_code'] = kline_df['code'].str.split('.').str[1]
            latest_kline = kline_df.sort_values('date').groupby('pure_code').tail(1).set_index('pure_code')
            for col, target in [('turn', 'turnover_rate_value'), ('peTTM', 'pe_ttm')]:
                if col in latest_kline.columns:
                    df[target] = latest_kline[col]

            # 10. 计算MACD信号（逐只股票）
            macd_results: dict[str, dict] = {}
            for pc, group in kline_df.groupby('pure_code'):
                close_series = group.sort_values('date')['close']
                macd_results[pc] = _compute_macd(close_series)
            df['macd_signal'] = df.index.map(lambda x: macd_results.get(x, {}).get('signal'))
            df['macd_score_raw'] = df.index.map(lambda x: macd_results.get(x, {}).get('score'))

        # 11. 计算北向资金得分
        if not northbound_df.empty:
            nb_scored = cls._process_northbound(northbound_df, df.index.tolist())
            if nb_scored is not None:
                df['northbound_net'] = nb_scored['northbound_net']
            else:
                degraded_factors.append('northbound')
        else:
            df['northbound_net'] = np.nan

        # 12. 计算PEG
        df['peg_value'] = np.nan
        if 'pe_ttm' in df.columns and 'profit_growth_value' in df.columns:
            mask_valid = (df['profit_growth_value'] > 0) & (df['pe_ttm'] > 0)
            df.loc[mask_valid, 'peg_value'] = df.loc[mask_valid, 'pe_ttm'] / df.loc[mask_valid, 'profit_growth_value']

        # 13. 行业景气打分：按行业聚合YOYNI中位数
        df['industry_score'] = 50.0
        if 'industry_name' in df.columns and 'profit_growth_value' in df.columns:
            industry_growth = df.groupby('industry_name')['profit_growth_value'].median()
            df['industry_growth'] = df['industry_name'].map(industry_growth)
            industry_scores = _percentile_score(industry_growth)
            df['industry_score'] = df['industry_name'].map(industry_scores).fillna(50.0)

        # 14. 各因子分位数打分
        score_map = {
            'roe_score': ('roe_value', False),
            'peg_score': ('peg_value', True),  # PEG越低越好
            'profit_growth_score': ('profit_growth_value', False),
            'volume_score': ('turnover_rate_value', False),
            'northbound_score': ('northbound_net', False),
        }
        for score_col, (value_col, reverse) in score_map.items():
            if value_col in df.columns:
                # 因子原始值缺失时使用中性分50，避免总分被NaN污染。
                df[score_col] = _percentile_score(df[value_col], reverse=reverse).fillna(50.0)
            else:
                df[score_col] = 50.0

        # MACD得分直接用规则打分
        if 'macd_score_raw' in df.columns:
            df['macd_score'] = df['macd_score_raw']
        else:
            df['macd_score'] = 50.0

        # 16. 北向降级处理
        if 'northbound' in degraded_factors:
            df['northbound_score'] = 50.0

        # 17. 计算总分
        score_columns = [
            'roe_score', 'peg_score', 'profit_growth_score', 'volume_score',
            'macd_score', 'northbound_score', 'industry_score',
        ]
        for col in score_columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(50.0)

        df['total_score'] = (
            df['roe_score'] * weights['roe'] / 100
            + df['peg_score'] * weights['peg'] / 100
            + df['profit_growth_score'] * weights['profit_growth'] / 100
            + df['volume_score'] * weights['volume'] / 100
            + df['macd_score'] * weights['macd'] / 100
            + df['northbound_score'] * weights['northbound'] / 100
            + df['industry_score'] * weights['industry'] / 100
        ).fillna(50.0).round(2)

        # 18. 标记入选
        df['selected'] = (df['total_score'] >= selected_threshold).astype(int)
        df['factor_degraded'] = ','.join(degraded_factors) if degraded_factors else None
        df['batch_id'] = batch_id
        df['calc_date'] = date.today()
        df['code'] = df.index  # pure_code

        # 19. 重置索引并入库
        df = df.reset_index().rename(columns={'index': 'pure_code'})

        # 20. 过滤有效行
        valid_cols = ['roe_score', 'peg_score', 'profit_growth_score', 'volume_score',
                      'macd_score', 'northbound_score', 'industry_score']
        has_any_score = df[valid_cols].notna().any(axis=1)
        df = df[has_any_score].copy()

        # 21. 构建入库对象
        records = []
        for _, row in df.iterrows():
            record = MultiFactorResult(
                batch_id=batch_id,
                code=str(row['pure_code'])[:6],
                name=_safe_str(row.get('name')),
                total_score=float(row.get('total_score', 0)),
                roe_score=_safe_float(row.get('roe_score')),
                peg_score=_safe_float(row.get('peg_score')),
                profit_growth_score=_safe_float(row.get('profit_growth_score')),
                volume_score=_safe_float(row.get('volume_score')),
                macd_score=_safe_float(row.get('macd_score')),
                northbound_score=_safe_float(row.get('northbound_score')),
                industry_score=_safe_float(row.get('industry_score')),
                roe_value=_safe_float(row.get('roe_value'), _DECIMAL_10_4_MAX_ABS, 4),
                peg_value=_safe_float(row.get('peg_value'), _DECIMAL_10_4_MAX_ABS, 4),
                profit_growth_value=_safe_float(row.get('profit_growth_value'), _DECIMAL_10_4_MAX_ABS, 4),
                turnover_rate_value=_safe_float(row.get('turnover_rate_value'), _DECIMAL_10_4_MAX_ABS, 4),
                macd_signal=_safe_str(row.get('macd_signal')),
                northbound_net=_safe_float(row.get('northbound_net'), 99999999999999.99, 2),
                industry_name=_safe_str(row.get('industry_name')),
                industry_growth=_safe_float(row.get('industry_growth'), _DECIMAL_10_4_MAX_ABS, 4),
                selected=int(row.get('selected', 0)),
                factor_degraded=_safe_str(row.get('factor_degraded')),
                calc_date=date.today(),
            )
            records.append(record)

        if not records:
            raise ServiceException(message='计算结果为空，请检查数据源')

        await MultiFactorDao.bulk_create(db, records)
        await db.commit()

        elapsed = time.time() - start_time
        selected_count = int(df['selected'].sum())
        logger.info(
            f'多因子计算完成 batch={batch_id} 总数={len(records)} 入选={selected_count} '
            f'耗时={elapsed:.1f}s 降级因子={degraded_factors}'
        )

        return MultiFactorCalcResultModel(
            batch_id=batch_id,
            total_count=len(records),
            selected_count=selected_count,
            degraded_factors=degraded_factors,
            calc_date=date.today(),
            elapsed_seconds=round(elapsed, 1),
        )

    @classmethod
    def _process_northbound(cls, nb_df: pd.DataFrame, all_codes: list[str]) -> dict[str, float] | None:
        """处理北向持仓数据，返回 {pure_code: change_value}。

        数据来自 eastmoney stock_hsgt_hold_stock_em，字段包含：
        - 代码/名称
        - 今日持股市值（当前持仓市值）
        - 今日新增持股-市值 或 季度新增持股-市值（持仓变化）
        """
        try:
            # 找代码列
            code_col = None
            for col in nb_df.columns:
                if "代码" in str(col):
                    code_col = col
                    break
            if code_col is None:
                return None

            # 找持仓变化列（优先找"新增持股"相关，其次找"持股市值"）
            change_col = None
            for col in nb_df.columns:
                col_str = str(col)
                if "新增持股" in col_str and "市值" in col_str and "变化" not in col_str:
                    change_col = col
                    break
            if change_col is None:
                for col in nb_df.columns:
                    col_str = str(col)
                    if "新增持股" in col_str and "数量" in col_str:
                        change_col = col
                        break
            if change_col is None:
                # 降级：用持股市值作为绝对值参考
                for col in nb_df.columns:
                    col_str = str(col)
                    if "持股市值" in col_str and "占比" not in col_str:
                        change_col = col
                        break
            if change_col is None:
                return None

            nb_df = nb_df.copy()
            nb_df["pure_code"] = nb_df[code_col].astype(str).str.extract(r"(\d{6})")
            nb_df["_value"] = pd.to_numeric(nb_df[change_col], errors="coerce")
            nb_sub = nb_df.dropna(subset=["pure_code", "_value"]).set_index("pure_code")["_value"]
            # 转为dict，为没有北向数据的股票填0
            nb_dict = nb_sub.to_dict()
            result = {code: nb_dict.get(code, 0.0) for code in all_codes}
            return result
        except Exception as exc:
            logger.warning(f"北向持仓处理失败: {exc}")
            return None
            # 找持股变动相关列
            change_col = None
            for col in nb_df.columns:
                col_str = str(col)
                if '持股市值' in col_str or '增持' in col_str or '净买入' in col_str:
                    change_col = col
                    break
            if change_col is None:
                return None

            nb_df = nb_df.copy()
            nb_df['pure_code'] = nb_df[code_col].astype(str).str.extract(r'(\d{6})')
            nb_df['_value'] = pd.to_numeric(nb_df[change_col], errors='coerce')
            nb_sub = nb_df.dropna(subset=['pure_code', '_value']).set_index('pure_code')['_value']
            result = all_codes and nb_sub.to_dict() or {}
            # 为没有北向数据的股票填0
            final = {code: result.get(code, 0.0) for code in all_codes}
            return final
        except Exception as exc:
            logger.warning(f'北向资金处理失败: {exc}')
            return None

    @classmethod
    async def list_results(cls, db: AsyncSession, query: MultiFactorResultQueryModel) -> PageModel:
        """查询计算结果。"""
        batch_id = query.batch_id
        if not batch_id:
            batch_id = await MultiFactorDao.get_latest_batch_id(db)
            if not batch_id:
                return PageModel(rows=[], pageNum=query.page_num, pageSize=query.page_size, hasNext=False, total=0)
        return await MultiFactorDao.list_page(db, query, batch_id)

    @classmethod
    async def get_latest_batch(cls, db: AsyncSession) -> MultiFactorBatchInfoModel | None:
        """获取最新批次信息。"""
        batch_id = await MultiFactorDao.get_latest_batch_id(db)
        if not batch_id:
            return None
        info = await MultiFactorDao.get_batch_info(db, batch_id)
        return MultiFactorBatchInfoModel(**info)

    @classmethod
    async def add_selected_to_pool(cls, db: AsyncSession, request: MultiFactorPoolAddRequestModel) -> MultiFactorPoolAddResultModel:
        """将入选股票批量加入股票池。"""
        batch_id = request.batch_id
        if not batch_id:
            batch_id = await MultiFactorDao.get_latest_batch_id(db)
            if not batch_id:
                raise ServiceException(message='没有可用的计算结果，请先执行计算')

        selected_threshold = await MultiFactorDao.get_selected_threshold(db)

        selected_codes: list[str] | None = None
        if request.codes is not None:
            selected_codes = list(dict.fromkeys(code.strip() for code in request.codes))
            invalid_codes = [code for code in selected_codes if len(code) != 6 or not code.isdigit()]
            if invalid_codes:
                raise ServiceException(message=f'股票代码格式错误: {",".join(invalid_codes[:10])}')

        results = await MultiFactorDao.get_selected_results(db, batch_id, selected_codes)
        if not results:
            if selected_codes is not None:
                raise ServiceException(message='所选股票中没有当前批次的入选股票')
            raise ServiceException(message=f'该批次没有入选股票（>={selected_threshold:g}分）')

        added_count = 0
        skipped_count = 0
        for item in results:
            existing = await StockPoolDao.get_existing_codes(db, request.pool_name, [item.code])
            if item.code in existing:
                skipped_count += 1
                continue
            from module_stock.entity.do.stock_selector_do import StockPoolItem
            await StockPoolDao.create(db, StockPoolItem(
                pool_name=request.pool_name,
                code=item.code,
                name=item.name,
                source_query=f'多因子选股 batch={batch_id} score={item.total_score}',
                source='multi_factor',
                remark=f'总分{item.total_score}',
            ))
            added_count += 1

        await db.commit()
        return MultiFactorPoolAddResultModel(
            pool_name=request.pool_name,
            requested_count=len(results),
            added_count=added_count,
            skipped_count=skipped_count,
        )

    @classmethod
    async def _get_weight_config_map(cls, db: AsyncSession) -> dict[str, dict]:
        """获取全部因子配置；缺失的因子使用默认配置。"""
        config_map = {
            name: {'weight': float(weight), 'enabled': True}
            for name, weight in _DEFAULT_WEIGHTS.items()
        }
        config_rows = await MultiFactorDao.get_all_weights(db)
        for row in config_rows:
            if row.factor_name not in config_map:
                continue
            config_map[row.factor_name] = {
                'weight': float(row.factor_weight),
                'enabled': bool(row.enabled),
            }
        return config_map

    @classmethod
    async def _get_effective_weights(cls, db: AsyncSession) -> dict[str, float]:
        """获取计算用权重；禁用因子权重为0。"""
        config_map = await cls._get_weight_config_map(db)
        return {
            name: float(config['weight']) if config['enabled'] else 0.0
            for name, config in config_map.items()
        }

    @classmethod
    async def get_calc_settings(cls, db: AsyncSession) -> MultiFactorWeightSettingsModel:
        """获取多因子计算配置（因子权重和入选阈值）。"""
        config_map = await cls._get_weight_config_map(db)
        selected_threshold = await MultiFactorDao.get_selected_threshold(db)
        return MultiFactorWeightSettingsModel(
            selected_threshold=selected_threshold,
            weights=[
                MultiFactorFactorWeightModel(
                    factor_name=name,
                    factor_label=FACTOR_LABELS.get(name, name),
                    weight=config['weight'],
                    enabled=config['enabled'],
                )
                for name, config in config_map.items()
            ],
        )

    @classmethod
    async def update_calc_settings(cls, db: AsyncSession, request: MultiFactorWeightSaveRequestModel) -> MultiFactorWeightSettingsModel:
        """保存前端提交的因子权重和入选阈值。"""
        valid_names = set(FACTOR_LABELS)
        submitted_names = {item.factor_name for item in request.weights}
        if len(request.weights) != len(valid_names) or submitted_names != valid_names:
            raise ServiceException(message='因子权重配置不完整或包含未知因子')

        enabled_total = round(sum(
            round(float(item.weight), 2)
            for item in request.weights
            if item.enabled
        ), 2)
        if abs(enabled_total - 100.0) > 0.01:
            raise ServiceException(message=f'启用因子权重合计必须为100%，当前为{enabled_total}%')

        await MultiFactorDao.update_weights(db, request.weights)
        await MultiFactorDao.update_selected_threshold(db, request.selected_threshold)
        await db.commit()
        return await cls.get_calc_settings(db)


# decimal(10,4) 可安全入库的最大绝对值（预留四舍五入空间）。
_DECIMAL_10_4_MAX_ABS = 999999.9994


def _safe_str(value) -> str | None:
    """安全转换为str或None，避免pandas的NaN进入MySQL字符串字段。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    value = str(value).strip()
    return value or None


def _safe_float(value, max_abs: float | None = None, decimals: int | None = None) -> float | None:
    """安全转换为float或None，并按MySQL decimal字段精度处理。"""
    if value is None:
        return None
    try:
        result = float(value)
        if np.isnan(result) or np.isinf(result):
            return None
        if max_abs is not None and abs(result) > max_abs:
            return None
        if decimals is not None:
            result = round(result, decimals)
        return result
    except (ValueError, TypeError):
        return None
