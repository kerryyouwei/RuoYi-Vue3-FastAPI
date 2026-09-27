from datetime import date as date_type

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class StockDayDateQueryModel(BaseModel):
    """
    股票日线日期查询参数模型
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, str_strip_whitespace=True)

    code: str = Field(default='002594', min_length=6, max_length=6, description='股票代码')
    start: date_type = Field(default=date_type(2025, 1, 1), description='开始日期')
    end: date_type = Field(default=date_type(2026, 3, 31), description='结束日期')
    @field_validator('code')
    @classmethod
    def validate_code(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError('股票代码必须为6位数字')
        return value

    @model_validator(mode='after')
    def validate_date_range(self) -> 'StockDayQueryModel':
        if self.start > self.end:
            raise ValueError('开始日期不能晚于结束日期')
        return self


class StockDayQueryModel(StockDayDateQueryModel):
    """
    股票日线分页查询参数模型
    """

    page_num: int = Field(default=1, ge=1, description='当前页码')
    page_size: int = Field(default=10, ge=1, le=100, description='每页记录数')


class StockDayImportModel(StockDayDateQueryModel):
    """
    股票日线导入参数模型
    """


class StockDayModel(BaseModel):
    """
    股票日线数据模型
    """

    date: date_type = Field(description='交易日期')
    code: str = Field(description='股票代码')
    open: float = Field(description='开盘价')
    high: float = Field(description='最高价')
    low: float = Field(description='最低价')
    close: float = Field(description='收盘价')
    volume: float = Field(description='成交量')
    amount: float = Field(description='成交额')


class StockDayImportResultModel(BaseModel):
    """
    股票日线导入结果模型
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    code: str = Field(description='股票代码')
    start: date_type = Field(description='开始日期')
    end: date_type = Field(description='结束日期')
    fetched_count: int = Field(description='获取数据条数')
    inserted_count: int = Field(description='新增数据条数')
    updated_count: int = Field(description='更新数据条数')
    message: str = Field(description='导入提示信息')
