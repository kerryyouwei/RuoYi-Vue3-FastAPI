from typing import Any

import anyio

from common.vo import PageModel
from exceptions.exception import ServiceException
from module_stock.entity.vo.stock_list_vo import (
    StockListImportResultModel,
    StockListModel,
    StockListQueryModel,
)
from utils.page_util import PageUtil


class StockListService:
    """
    股票列表服务层
    """

    @classmethod
    async def get_stock_list(cls, query: StockListQueryModel) -> PageModel[StockListModel]:
        return await anyio.to_thread.run_sync(cls._fetch_stock_list, query)

    @classmethod
    async def import_stock_list(cls) -> StockListImportResultModel:
        return await anyio.to_thread.run_sync(cls._import_stock_list)

    @staticmethod
    def _fetch_stock_list(query: StockListQueryModel) -> PageModel[StockListModel]:
        try:
            import QUANTAXIS as QA  # noqa: PLC0415
        except ImportError as exc:
            raise ServiceException(message='QUANTAXIS未安装，无法查询股票列表') from exc

        try:
            records = list(QA.DATABASE.stock_list.find({}, {'_id': 0}).sort('code', 1))
        except Exception as exc:
            raise ServiceException(message='MongoDB股票列表查询失败') from exc

        if not records:
            raise ServiceException(message='未查询到股票列表数据，请先获取数据')

        stock_list = []
        for record in records:
            model = StockListService._build_stock_list_model(record)
            if model and StockListService._matches_query(model, query):
                stock_list.append(model)

        if not stock_list:
            raise ServiceException(message='未查询到符合条件的股票列表数据')

        return PageUtil.get_page_obj(stock_list, query.page_num, query.page_size)

    @staticmethod
    def _import_stock_list() -> StockListImportResultModel:
        try:
            import QUANTAXIS as QA  # noqa: PLC0415
            from pymongo import UpdateOne  # noqa: PLC0415
        except ImportError as exc:
            raise ServiceException(message='QUANTAXIS或pymongo未安装，无法导入股票列表') from exc

        try:
            frame = QA.QA_fetch_get_stock_list(package='baostock')
        except Exception as exc:
            raise ServiceException(message='从Baostock获取股票列表失败') from exc

        if frame is None or frame.empty:
            raise ServiceException(message='未从Baostock获取到股票列表数据')

        try:
            frame = StockListService._normalize_stock_frame(frame)
            records = QA.QA_util_to_json_from_pandas(frame.reset_index(drop=True))
            collection = QA.DATABASE.stock_list
            collection.create_index([('code', 1)])
            operations = [
                UpdateOne({'code': record['code']}, {'$set': record}, upsert=True)
                for record in records
            ]
            result = collection.bulk_write(operations, ordered=False) if operations else None
        except ServiceException:
            raise
        except Exception as exc:
            raise ServiceException(message='股票列表写入MongoDB失败') from exc

        inserted_count = result.upserted_count if result else 0
        updated_count = result.modified_count if result else 0
        fetched_count = len(records)
        message = (
            f'A股股票列表导入MongoDB完成，共获取{fetched_count}条，'
            f'新增{inserted_count}条，更新{updated_count}条'
        )
        return StockListImportResultModel(
            fetched_count=fetched_count,
            inserted_count=inserted_count,
            updated_count=updated_count,
            message=message,
        )

    @staticmethod
    def _normalize_stock_frame(frame: Any) -> Any:
        rename_map = {
            'code_name': 'name',
            'stock_name': 'name',
            'ipo_date': 'ipoDate',
            'out_date': 'outDate',
        }
        renames = {
            source: target
            for source, target in rename_map.items()
            if source in frame.columns and target not in frame.columns
        }
        frame = frame.rename(columns=renames)
        if 'code' not in frame.columns:
            raise ServiceException(message='Baostock返回数据缺少code字段')

        frame = frame.copy()
        frame['code'] = frame['code'].astype(str)
        return frame

    @staticmethod
    def _matches_query(model: StockListModel, query: StockListQueryModel) -> bool:
        if query.code and query.code.lower() not in model.code.lower():
            return False
        if query.name and query.name.lower() not in model.name.lower():
            return False
        return not (query.sse and model.sse.lower() != query.sse.lower())

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ''
        text = str(value).strip()
        if text.lower() in {'', 'nan', 'none', 'nat'}:
            return ''
        return text

    @staticmethod
    def _clean_optional_text(value: Any) -> str | None:
        text = StockListService._clean_text(value)
        return text or None

    @staticmethod
    def _clean_optional_date(value: Any) -> str | None:
        text = StockListService._clean_text(value)
        return text[:10] if text else None

    @staticmethod
    def _build_stock_list_model(record: dict[str, Any]) -> StockListModel | None:
        code = StockListService._clean_text(record.get('code'))
        if not code:
            return None

        name = (
            StockListService._clean_text(record.get('name'))
            or StockListService._clean_text(record.get('code_name'))
            or StockListService._clean_text(record.get('stock_name'))
        )
        sse = (
            StockListService._clean_text(record.get('sse'))
            or StockListService._clean_text(record.get('market'))
            or StockListService._clean_text(record.get('exchange'))
        ).lower()
        status = StockListService._clean_text(record.get('status'))
        if status in {'1', '1.0'}:
            status = '1'
        elif status in {'0', '0.0'}:
            status = '0'
        if not status:
            status = '1'

        return StockListModel(
            code=code,
            name=name,
            sse=sse,
            ipo_date=(
                StockListService._clean_optional_date(record.get('ipoDate'))
                or StockListService._clean_optional_date(record.get('ipo_date'))
            ),
            out_date=(
                StockListService._clean_optional_date(record.get('outDate'))
                or StockListService._clean_optional_date(record.get('out_date'))
            ),
            status=status,
        )







