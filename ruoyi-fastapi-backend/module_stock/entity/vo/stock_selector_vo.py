from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class SelectorBaseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, str_strip_whitespace=True)


class SelectorSearchQueryModel(SelectorBaseModel):
    """问财智能选股查询条件。"""

    custom_query: str | None = Field(default=None, max_length=1000, description='自定义问财查询语句')
    price_min: float | None = Field(default=None, ge=0, le=1_000_000, description='最新价下限')
    price_max: float | None = Field(default=None, ge=0, le=1_000_000, description='最新价上限')
    pct_change_min: float | None = Field(default=None, ge=-100, le=100, description='昨日涨跌幅下限')
    pct_change_max: float | None = Field(default=None, ge=-100, le=100, description='昨日涨跌幅上限')
    amount_min: float | None = Field(default=None, ge=0, le=1_000_000, description='昨日成交额下限，单位亿元')
    turnover_rate_min: float | None = Field(default=None, ge=0, le=100, description='昨日换手率下限')
    turnover_rate_max: float | None = Field(default=None, ge=0, le=100, description='昨日换手率上限')
    macd_golden_cross: bool = Field(default=False, description='是否筛选MACD金叉')
    page_num: int = Field(default=1, ge=1, description='当前页码')
    page_size: int = Field(default=20, ge=1, le=100, description='每页记录数')

    @field_validator('custom_query', mode='before')
    @classmethod
    def normalize_custom_query(cls, value: Any) -> Any:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode='after')
    def validate_query(self) -> 'SelectorSearchQueryModel':
        has_condition = any(
            value is not None
            for value in (
                self.custom_query,
                self.price_min,
                self.price_max,
                self.pct_change_min,
                self.pct_change_max,
                self.amount_min,
                self.turnover_rate_min,
                self.turnover_rate_max,
                self.macd_golden_cross,
            )
        )
        if not has_condition:
            raise ValueError('请至少填写一个选股条件')
        for lower, upper, message in (
            (self.price_min, self.price_max, '最新价'),
            (self.pct_change_min, self.pct_change_max, '昨日涨跌幅'),
            (self.turnover_rate_min, self.turnover_rate_max, '昨日换手率'),
        ):
            if lower is not None and upper is not None and lower > upper:
                raise ValueError(f'{message}下限不能大于上限')
        return self


class AStockResultModel(BaseModel):
    """规范化后的问财股票结果。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    code: str = Field(description='6位股票代码')
    name: str | None = Field(default=None, description='股票简称')
    market: str | None = Field(default=None, description='市场后缀')
    raw: dict[str, Any] = Field(default_factory=dict, description='问财原始返回字段')


class AStockSearchResultModel(BaseModel):
    """问财选股分页结果。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    query_text: str = Field(description='实际使用的问财查询语句')
    code_count: int = Field(default=0, description='符合条件的股票总数')
    page_num: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    has_more: bool = Field(default=False, description='是否有下一页')
    rows: list[AStockResultModel] = Field(default_factory=list)


class StockPoolAddItemModel(SelectorBaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r'^\d{6}$', description='股票代码')
    name: str | None = Field(default=None, max_length=100, description='股票简称')
    source_query: str | None = Field(default=None, max_length=2000, description='选股条件')
    remark: str | None = Field(default=None, max_length=255, description='备注')


class StockPoolAddRequestModel(SelectorBaseModel):
    pool_name: str = Field(default='default', min_length=1, max_length=64, description='股票池名称')
    items: list[StockPoolAddItemModel] = Field(min_length=1, max_length=100, description='股票列表')

    @field_validator('pool_name', mode='before')
    @classmethod
    def normalize_pool_name(cls, value: Any) -> Any:
        normalized = str(value or '').strip()
        return normalized or 'default'

    @field_validator('items')
    @classmethod
    def validate_items(cls, value: list[StockPoolAddItemModel]) -> list[StockPoolAddItemModel]:
        if not value:
            raise ValueError('请选择要加入股票池的股票')
        return value


class StockPoolAddResultModel(SelectorBaseModel):
    pool_name: str
    requested_count: int = Field(default=0, ge=0)
    added_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)


class StockPoolQueryModel(SelectorBaseModel):
    pool_name: str | None = Field(default=None, max_length=64, description='股票池名称')
    keyword: str | None = Field(default=None, max_length=100, description='代码或名称关键词')
    page_num: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)

    @field_validator('pool_name', 'keyword', mode='before')
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Any:
        normalized = str(value or '').strip()
        return normalized or None


class StockPoolItemModel(SelectorBaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    id: int
    pool_name: str
    code: str
    name: str | None = None
    source_query: str | None = None
    source: Literal['iwencai', 'manual', 'backtest'] = 'iwencai'
    remark: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None


class StockPoolNameModel(SelectorBaseModel):
    pool_name: str
    stock_count: int = Field(default=0, ge=0)

