import asyncio
import importlib.util
import math
import os
import re
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from exceptions.exception import ServiceException
from module_stock.dao.stock_pool_dao import StockPoolDao
from module_stock.entity.do.stock_selector_do import StockPoolItem
from module_stock.entity.vo.stock_selector_vo import (
    AStockResultModel,
    AStockSearchResultModel,
    SelectorSearchQueryModel,
    StockPoolAddItemModel,
    StockPoolAddRequestModel,
    StockPoolAddResultModel,
    StockPoolNameModel,
    StockPoolQueryModel,
)
from utils.log_util import logger

_CODE_PATTERN = re.compile(r'\d{6}')
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SELECTOR_PATH = _ROOT / 'youw_test' / 'astock-selector'
_SELECTOR_QUERY_TIMEOUT = 60


class StockSelectorService:
    """问财智能选股与股票池服务。"""

    _selector_module: Any | None = None

    @classmethod
    async def search(cls, query: SelectorSearchQueryModel) -> AStockSearchResultModel:
        return await asyncio.to_thread(cls._search, query)

    @classmethod
    async def add_to_pool(cls, db: AsyncSession, request: StockPoolAddRequestModel) -> StockPoolAddResultModel:
        unique_items: dict[str, StockPoolAddItemModel] = {}
        skipped_count = 0
        for item in request.items:
            if item.code in unique_items:
                skipped_count += 1
            else:
                unique_items[item.code] = item

        existing_codes = await StockPoolDao.get_existing_codes(db, request.pool_name, list(unique_items))
        added_count = 0
        for code, item in unique_items.items():
            if code in existing_codes:
                skipped_count += 1
                continue
            added_count += 1
            await StockPoolDao.create(
                db,
                StockPoolItem(
                    pool_name=request.pool_name,
                    code=code,
                    name=item.name,
                    source_query=item.source_query,
                    source='iwencai',
                    remark=item.remark,
                ),
            )

        await db.commit()
        return StockPoolAddResultModel(
            poolName=request.pool_name,
            requestedCount=len(request.items),
            addedCount=added_count,
            skippedCount=skipped_count,
        )

    @classmethod
    async def pool_list(cls, db: AsyncSession, query: StockPoolQueryModel) -> PageModel:
        return await StockPoolDao.list_page(db, query)

    @classmethod
    async def pool_names(cls, db: AsyncSession) -> list[StockPoolNameModel]:
        return await StockPoolDao.pool_names(db)

    @classmethod
    async def remove_pool_item(cls, db: AsyncSession, item_id: int) -> None:
        item = await StockPoolDao.get(db, item_id)
        if item is None:
            raise ServiceException(message='股票池记录不存在')
        await StockPoolDao.delete(db, item)
        await db.commit()

    @classmethod
    def _search(cls, query: SelectorSearchQueryModel) -> AStockSearchResultModel:
        if not os.getenv('IWENCAI_API_KEY'):
            raise ServiceException(message='未配置问财API Key：IWENCAI_API_KEY')
        query_text = cls._build_query_text(query)
        selector = cls._load_selector_module()
        try:
            result = selector.query_astock(
                query=query_text,
                page=query.page_num,
                limit=query.page_size,
                timeout=_SELECTOR_QUERY_TIMEOUT,
            )
        except ServiceException:
            raise
        except Exception as exc:
            logger.bind(query=query_text).exception('问财选股查询失败')
            raise ServiceException(message='问财选股查询失败，请稍后重试') from exc

        if not isinstance(result, dict) or 'datas' not in result:
            detail = result.get('message') or result.get('msg') if isinstance(result, dict) else str(result)
            raise ServiceException(message=f'问财选股返回异常：{detail or "缺少datas数据"}')

        raw_rows = result.get('datas') or []
        if not isinstance(raw_rows, list):
            raise ServiceException(message='问财选股返回的datas字段格式错误')

        rows = cls._build_rows(raw_rows)
        try:
            code_count = int(result.get('code_count') or 0)
        except (TypeError, ValueError) as exc:
            raise ServiceException(message='问财选股返回的股票总数格式错误') from exc
        return AStockSearchResultModel(
            queryText=query_text,
            codeCount=max(code_count, 0),
            pageNum=query.page_num,
            pageSize=query.page_size,
            hasMore=query.page_num * query.page_size < max(code_count, 0),
            rows=rows,
        )

    @classmethod
    def _load_selector_module(cls) -> Any:
        if cls._selector_module is not None:
            return cls._selector_module

        selector_path = Path(os.getenv('ASTOCK_SELECTOR_PATH', str(_DEFAULT_SELECTOR_PATH)))
        if not selector_path.is_file():
            raise ServiceException(message=f'问财选股数据源文件不存在：{selector_path}')

        loader = SourceFileLoader('youw_astock_selector', str(selector_path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        if spec is None:
            raise ServiceException(message='问财选股数据源加载失败')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            loader.exec_module(module)
        except Exception as exc:
            raise ServiceException(message='问财选股数据源加载失败，请检查ASTOCK_SELECTOR_PATH配置') from exc
        cls._selector_module = module
        return module

    @staticmethod
    def _build_query_text(query: SelectorSearchQueryModel) -> str:
        clauses: list[str] = []

        def append_range(lower: float | None, upper: float | None, label: str, unit: str = '') -> None:
            if lower is not None:
                clauses.append(f'{label}大于等于{StockSelectorService._format_number(lower)}{unit}')
            if upper is not None:
                clauses.append(f'{label}小于等于{StockSelectorService._format_number(upper)}{unit}')

        append_range(query.price_min, query.price_max, '最新价', '元')
        append_range(query.pct_change_min, query.pct_change_max, '昨日涨跌幅', '%')
        if query.amount_min is not None:
            clauses.append(f'昨日成交额大于等于{StockSelectorService._format_number(query.amount_min)}亿元')
        append_range(query.turnover_rate_min, query.turnover_rate_max, '昨日换手率', '%')
        if query.macd_golden_cross:
            clauses.append('MACD金叉')
        if query.custom_query:
            clauses.append(query.custom_query)

        return '，'.join(clauses)

    @classmethod
    def _build_rows(cls, raw_rows: list[Any]) -> list[AStockResultModel]:
        rows: list[AStockResultModel] = []
        seen_codes: set[str] = set()
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue
            code, market = cls._extract_code(raw_row)
            if code is None or code in seen_codes:
                continue
            seen_codes.add(code)
            name = cls._extract_name(raw_row)
            rows.append(
                AStockResultModel(
                    code=code,
                    name=name,
                    market=market,
                    raw={str(key): cls._clean_json_value(value) for key, value in raw_row.items()},
                )
            )
        return rows

    @staticmethod
    def _extract_code(row: dict[str, Any]) -> tuple[str | None, str | None]:
        value = row.get('股票代码')
        if value is None:
            for key, candidate in row.items():
                if '代码' in str(key):
                    value = candidate
                    break
        if value is None:
            return None, None
        matched = _CODE_PATTERN.search(str(value))
        if matched is None:
            return None, None
        text = str(value)
        market = text.split('.', 1)[1].upper() if '.' in text else None
        return matched.group(0), market

    @staticmethod
    def _extract_name(row: dict[str, Any]) -> str | None:
        value = row.get('股票简称')
        if value is None:
            for key, candidate in row.items():
                key_text = str(key)
                if ('简称' in key_text or '名称' in key_text) and '代码' not in key_text:
                    value = candidate
                    break
        if value is None:
            return None
        name = str(value).strip()
        return name or None

    @staticmethod
    def _clean_json_value(value: Any) -> Any:
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, dict):
            return {str(key): StockSelectorService._clean_json_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [StockSelectorService._clean_json_value(item) for item in value]
        return value

    @staticmethod
    def _format_number(value: float) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return f'{value:g}'







