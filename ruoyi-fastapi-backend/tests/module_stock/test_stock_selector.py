from typing import Any

import pytest
from pydantic import ValidationError

from exceptions.exception import ServiceException
from module_stock.dao.stock_pool_dao import StockPoolDao
from module_stock.entity.do.stock_selector_do import StockPoolItem
from module_stock.entity.vo.stock_selector_vo import (
    SelectorSearchQueryModel,
    StockPoolAddItemModel,
    StockPoolAddRequestModel,
)
from module_stock.service.stock_selector_service import StockSelectorService

PAGE_NUMBER = 2
PAGE_SIZE = 20
QUERY_TIMEOUT = 60
TOTAL_COUNT = 25
RAW_PRICE = 12.3
CLEAN_NUMBER = 1.25
REQUESTED_COUNT = 3
SKIPPED_COUNT = 2


def test_selector_query_builds_conditions_in_stable_order() -> None:
    query = SelectorSearchQueryModel(
        custom_query='所属概念包含人工智能',
        price_min=5,
        price_max=20.5,
        pct_change_min=1,
        pct_change_max=7,
        amount_min=5,
        turnover_rate_min=5,
        turnover_rate_max=15,
        macd_golden_cross=True,
    )

    query_text = StockSelectorService._build_query_text(query)

    assert query_text == (
        '最新价大于等于5元，最新价小于等于20.5元，'
        '昨日涨跌幅大于等于1%，昨日涨跌幅小于等于7%，'
        '昨日成交额大于等于5亿元，'
        '昨日换手率大于等于5%，昨日换手率小于等于15%，'
        'MACD金叉，所属概念包含人工智能'
    )


def test_selector_query_requires_one_condition() -> None:
    with pytest.raises(ValidationError):
        SelectorSearchQueryModel()


def test_selector_query_rejects_reversed_range() -> None:
    with pytest.raises(ValidationError):
        SelectorSearchQueryModel(price_min=20, price_max=5)


def test_selector_rows_normalize_code_and_preserve_raw_data() -> None:
    rows = StockSelectorService._build_rows(
        [
            {'股票代码': '002840.SZ', '股票简称': '华统股份', '最新价': RAW_PRICE},
            {'股票代码': '000001', '股票简称': '平安银行', '最新价': 10.0},
            {'股票代码': '000001', '股票简称': '重复代码'},
            {'股票名称': '无效记录'},
            'not-a-dict',
        ]
    )

    assert [row.code for row in rows] == ['002840', '000001']
    assert rows[0].market == 'SZ'
    assert rows[0].name == '华统股份'
    assert rows[0].raw['最新价'] == RAW_PRICE
    assert rows[0].raw['股票代码'] == '002840.SZ'


def test_selector_non_finite_raw_value_is_cleaned() -> None:
    assert StockSelectorService._clean_json_value(float('nan')) is None
    assert StockSelectorService._clean_json_value(float('inf')) is None
    assert StockSelectorService._clean_json_value(CLEAN_NUMBER) == CLEAN_NUMBER


@pytest.mark.asyncio
async def test_search_wraps_selector_result(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSelector:
        @staticmethod
        def query_astock(query: str, page: int, limit: int, timeout: int) -> dict:
            assert query == '昨日涨跌幅大于等于1%'
            assert page == PAGE_NUMBER
            assert limit == PAGE_SIZE
            assert timeout == QUERY_TIMEOUT
            return {
                'datas': [{'股票代码': '600000.SH', '股票简称': '浦发银行'}],
                'code_count': TOTAL_COUNT,
            }

    monkeypatch.setattr(StockSelectorService, '_selector_module', FakeSelector)
    monkeypatch.setenv('IWENCAI_API_KEY', 'test-key')
    query = SelectorSearchQueryModel(
        pct_change_min=1,
        page_num=PAGE_NUMBER,
        page_size=PAGE_SIZE,
    )
    result = await StockSelectorService.search(query)

    assert result.query_text == '昨日涨跌幅大于等于1%'
    assert result.code_count == TOTAL_COUNT
    assert result.has_more is True
    assert result.rows[0].code == '600000'
    assert result.rows[0].market == 'SH'


def test_search_rejects_response_without_datas(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSelector:
        @staticmethod
        def query_astock(query: str, page: int, limit: int, timeout: int) -> dict:
            return {'code_count': 1}

    monkeypatch.setattr(StockSelectorService, '_selector_module', FakeSelector)
    monkeypatch.setenv('IWENCAI_API_KEY', 'test-key')
    query = SelectorSearchQueryModel(pct_change_min=1)

    with pytest.raises(ServiceException):
        StockSelectorService._search(query)


@pytest.mark.asyncio
async def test_add_to_pool_counts_request_duplicates_and_existing_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[StockPoolItem] = []

    async def fake_existing_codes(db: Any, pool_name: str, codes: list[str]) -> set[str]:
        assert pool_name == '成长池'
        assert codes == ['000001', '000002']
        return {'000001'}

    async def fake_create(db: Any, item: StockPoolItem) -> StockPoolItem:
        created.append(item)
        return item

    class FakeDb:
        async def commit(self) -> None:
            pass

    monkeypatch.setattr(StockPoolDao, 'get_existing_codes', fake_existing_codes)
    monkeypatch.setattr(StockPoolDao, 'create', fake_create)
    request = StockPoolAddRequestModel(
        poolName='成长池',
        items=[
            StockPoolAddItemModel(code='000001', name='平安银行'),
            StockPoolAddItemModel(code='000001', name='平安银行'),
            StockPoolAddItemModel(code='000002', name='万科A'),
        ],
    )

    result = await StockSelectorService.add_to_pool(FakeDb(), request)

    assert result.requested_count == REQUESTED_COUNT
    assert result.added_count == 1
    assert result.skipped_count == SKIPPED_COUNT
    assert [item.code for item in created] == ['000002']
    assert created[0].pool_name == '成长池'


def test_pool_add_request_rejects_invalid_code() -> None:
    with pytest.raises(ValidationError):
        StockPoolAddRequestModel(items=[StockPoolAddItemModel(code='00001A')])

