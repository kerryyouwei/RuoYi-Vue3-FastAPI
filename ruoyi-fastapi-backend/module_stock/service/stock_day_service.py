from datetime import date as date_type
from typing import Any

import anyio

from common.vo import PageModel
from exceptions.exception import ServiceException
from module_stock.entity.vo.stock_day_vo import (
    StockDayImportModel,
    StockDayImportResultModel,
    StockDayModel,
    StockDayQueryModel,
)
from utils.page_util import PageUtil


class StockDayService:
    """
    股票日线数据服务层
    """

    @classmethod
    async def get_stock_day_list(cls, query: StockDayQueryModel) -> PageModel[StockDayModel]:
        return await anyio.to_thread.run_sync(cls._fetch_stock_day_list, query)

    @classmethod
    async def import_stock_day_data(cls, query: StockDayImportModel) -> StockDayImportResultModel:
        return await anyio.to_thread.run_sync(cls._import_stock_day_data, query)

    @staticmethod
    def _fetch_stock_day_list(query: StockDayQueryModel) -> PageModel[StockDayModel]:
        try:
            import QUANTAXIS as QA  # noqa: PLC0415
        except ImportError as exc:
            raise ServiceException(message='QUANTAXIS未安装，无法查询股票日线数据') from exc

        start = query.start.isoformat()
        end = query.end.isoformat()

        try:
            data = QA.QA_fetch_stock_day_adv(query.code, start, end)
        except Exception as exc:
            raise ServiceException(message='MongoDB股票日线数据查询失败') from exc

        if data is None or data.data.empty:
            raise ServiceException(message=f'未查询到股票{query.code}在{start}至{end}的日线数据')

        frame = data.data.reset_index()
        if 'volume' not in frame.columns and 'vol' in frame.columns:
            frame = frame.rename(columns={'vol': 'volume'})

        required_columns = {'date', 'code', 'open', 'high', 'low', 'close', 'volume', 'amount'}
        missing_columns = required_columns.difference(frame.columns)
        if missing_columns:
            missing_text = '、'.join(sorted(missing_columns))
            raise ServiceException(message=f'MongoDB股票日线数据缺少字段：{missing_text}')

        stock_day_list = [StockDayService._build_stock_day_model(record) for record in frame.to_dict(orient='records')]
        return PageUtil.get_page_obj(stock_day_list, query.page_num, query.page_size)

    @staticmethod
    def _import_stock_day_data(query: StockDayImportModel) -> StockDayImportResultModel:
        try:
            import QUANTAXIS as QA  # noqa: PLC0415
            from pymongo import UpdateOne  # noqa: PLC0415
        except ImportError as exc:
            raise ServiceException(message='QUANTAXIS或pymongo未安装，无法导入股票日线数据') from exc

        start = query.start.isoformat()
        end = query.end.isoformat()

        try:
            data_frame = QA.QA_fetch_get_stock_day('baostock', query.code, start, end)
        except Exception as exc:
            raise ServiceException(message=f'从Baostock获取股票{query.code}日线数据失败') from exc

        if data_frame is None or data_frame.empty:
            raise ServiceException(message=f'未从Baostock获取到股票{query.code}在{start}至{end}的数据')

        mongo_frame = data_frame.copy()
        if 'volume' in mongo_frame.columns:
            mongo_frame = mongo_frame.rename(columns={'volume': 'vol'})
        if 'code' not in mongo_frame.columns or 'date' not in mongo_frame.columns:
            raise ServiceException(message='Baostock返回数据缺少code或date字段')

        mongo_frame['code'] = mongo_frame['code'].astype(str)
        mongo_frame['date'] = mongo_frame['date'].astype(str)

        try:
            records = QA.QA_util_to_json_from_pandas(mongo_frame.reset_index(drop=True))
            collection = QA.DATABASE.stock_day
            collection.create_index([('code', 1), ('date_stamp', 1)])
            operations = [
                UpdateOne(
                    {'code': record['code'], 'date_stamp': record['date_stamp']},
                    {'$set': record},
                    upsert=True,
                )
                for record in records
            ]
            result = collection.bulk_write(operations, ordered=False) if operations else None
        except Exception as exc:
            raise ServiceException(message='股票日线数据写入MongoDB失败') from exc

        inserted_count = result.upserted_count if result else 0
        updated_count = result.modified_count if result else 0
        fetched_count = len(records)
        message = (
            f'股票{query.code}从{start}至{end}的数据导入MongoDB完成，'
            f'共获取{fetched_count}条，新增{inserted_count}条，更新{updated_count}条'
        )
        return StockDayImportResultModel(
            code=query.code,
            start=query.start,
            end=query.end,
            fetched_count=fetched_count,
            inserted_count=inserted_count,
            updated_count=updated_count,
            message=message,
        )

    @staticmethod
    def _build_stock_day_model(record: dict[str, Any]) -> StockDayModel:
        record_date = record['date']
        if hasattr(record_date, 'date'):
            record_date = record_date.date()
        elif not isinstance(record_date, date_type):
            record_date = date_type.fromisoformat(str(record_date)[:10])

        return StockDayModel(
            date=record_date,
            code=str(record['code']),
            open=float(record['open']),
            high=float(record['high']),
            low=float(record['low']),
            close=float(record['close']),
            volume=float(record['volume']),
            amount=float(record['amount']),
        )
