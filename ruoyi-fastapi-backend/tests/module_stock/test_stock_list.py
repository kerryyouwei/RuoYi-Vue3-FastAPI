import pytest
from pydantic import ValidationError

from module_stock.entity.vo.stock_list_vo import (
    StockListImportResultModel,
    StockListQueryModel,
)
from module_stock.service.stock_list_service import StockListService

FETCHED_COUNT = 10
INSERTED_COUNT = 3
UPDATED_COUNT = 7


def test_stock_list_query_rejects_invalid_page_number() -> None:
    with pytest.raises(ValidationError):
        StockListQueryModel(pageNum=0)


def test_stock_list_record_mapping_supports_common_aliases() -> None:
    record = {
        'code': '000001',
        'code_name': '平安银行',
        'sse': 'SZ',
        'ipoDate': '1991-04-03',
        'outDate': None,
        'status': 1,
    }

    model = StockListService._build_stock_list_model(record)

    assert model is not None
    assert model.code == '000001'
    assert model.name == '平安银行'
    assert model.sse == 'sz'
    assert model.ipo_date == '1991-04-03'
    assert model.out_date is None
    assert model.status == '1'


def test_stock_list_record_without_code_is_skipped() -> None:
    assert StockListService._build_stock_list_model({'name': '测试'}) is None


def test_stock_list_query_matches_code_and_market() -> None:
    model = StockListService._build_stock_list_model(
        {'code': '000001', 'name': '平安银行', 'sse': 'sz', 'status': '1'}
    )
    query = StockListQueryModel(code='000001', sse='sz')

    assert model is not None
    assert StockListService._matches_query(model, query)


def test_stock_list_import_result_supports_camel_case_input() -> None:
    result = StockListImportResultModel(
        fetchedCount=FETCHED_COUNT,
        insertedCount=INSERTED_COUNT,
        updatedCount=UPDATED_COUNT,
        message='导入完成',
    )

    assert result.fetched_count == FETCHED_COUNT
    assert result.inserted_count == INSERTED_COUNT
    assert result.updated_count == UPDATED_COUNT
    assert result.message == '导入完成'

