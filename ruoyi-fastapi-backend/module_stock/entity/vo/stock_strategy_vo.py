from datetime import date as date_type
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class StrategyBaseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class StrategyQueryModel(StrategyBaseModel):
    strategy_name: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=32)
    status: Literal['pending', 'running', 'success', 'failed'] | None = None


class StrategyListModel(StrategyBaseModel):
    name: str
    display_name: str
    category: str
    description: str
    modified_time: str
    run_count: int = 0
    last_run_time: str | None = None
    last_return_rate: float | None = None
    last_status: str | None = None


class StrategyDetailModel(StrategyListModel):
    source_code: str
    parameters: list[dict[str, Any]] = Field(default_factory=list)


class StrategyRunRequest(StrategyBaseModel):
    strategy_name: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=6, max_length=6)
    start: date_type
    end: date_type
    initial_cash: int = Field(default=100000, ge=1000, le=10_000_000_000)
    commission_rate: float = Field(default=0.0003, ge=0, le=0.1)
    stamp_tax_rate: float = Field(default=0.001, ge=0, le=0.1)
    benchmark_code: str | None = Field(default=None, max_length=6)
    strategy_params: dict[str, Any] = Field(default_factory=dict)

    @field_validator('code', 'benchmark_code')
    @classmethod
    def validate_code(cls, value: str | None) -> str | None:
        if value is not None and value != '' and (not value.isdigit() or len(value) != 6):
            raise ValueError('股票代码必须为6位数字')
        return value or None

    @model_validator(mode='after')
    def validate_date_range(self) -> 'StrategyRunRequest':
        if self.start > self.end:
            raise ValueError('开始日期不能晚于结束日期')
        if self.start == self.end:
            raise ValueError('回测日期范围至少需要两个交易日')
        return self


class StrategyRunStatusModel(StrategyBaseModel):
    run_id: str
    strategy_name: str
    status: Literal['pending', 'running', 'success', 'failed']
    progress: int
    error_message: str | None = None
    summary: dict[str, Any] | None = None


class StrategyRunDetailModel(StrategyRunStatusModel):
    code: str
    start: str
    end: str
    initial_cash: int
    commission_rate: float
    stamp_tax_rate: float
    benchmark_code: str | None = None
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    create_time: datetime | None = None
    curves: dict[str, Any] | None = None
    trades: list[dict[str, Any]] | None = None
    logs: list[str] | None = None


class StrategyHistoryQueryModel(StrategyBaseModel):
    page_num: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)
