"""批量回测选股与模拟交易排序、请求与响应模型。"""

import re
from datetime import date as date_type
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class PaperBaseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


_CODE_LENGTH = 6

# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

class ScanRunRequestModel(PaperBaseModel):
    strategy_name: str = Field(min_length=1, max_length=64)
    pool_name: str = Field(min_length=1, max_length=64)
    start: date_type
    end: date_type
    initial_cash: int = Field(default=1_000_000, ge=1000, le=10_000_000_000)
    commission_rate: float = Field(default=0.0003, ge=0, le=0.1)
    stamp_tax_rate: float = Field(default=0.001, ge=0, le=0.1)
    benchmark_code: str | None = Field(default=None, max_length=6)
    strategy_params: dict[str, Any] = Field(default_factory=dict)

    @field_validator('pool_name', mode='before')
    @classmethod
    def normalize_pool_name(cls, value: Any) -> Any:
        normalized = str(value or '').strip()
        return normalized or 'default'

    @field_validator('benchmark_code')
    @classmethod
    def validate_code(cls, value: str | None) -> str | None:
        if value is not None and value != '' and (not value.isdigit() or len(value) != _CODE_LENGTH):
            raise ValueError('股票代码必须为6位数字')
        return value or None

    @model_validator(mode='after')
    def validate_date_range(self) -> 'ScanRunRequestModel':
        if self.start > self.end:
            raise ValueError('开始日期不能晚于结束日期')
        if self.start == self.end:
            raise ValueError('回测日期范围至少需要两个交易日')
        return self


class ScanBatchModel(PaperBaseModel):
    batch_id: str
    strategy_name: str
    pool_name: str
    start_date: str
    end_date: str
    initial_cash: int
    commission_rate: str
    stamp_tax_rate: str
    benchmark_code: str | None = None
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    status: Literal['pending', 'running', 'success', 'failed']
    progress: int
    total_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    error_message: str | None = None
    create_time: datetime | None = None


class ScanItemModel(PaperBaseModel):
    id: int
    batch_id: str
    code: str
    name: str | None = None
    status: Literal['pending', 'running', 'success', 'failed']
    summary: dict[str, Any] | None = None
    error_message: str | None = None
    return_rate: float | None = None
    annual_return: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None
    win_rate: float | None = None
    profit_loss_ratio: float | None = None
    trade_count: int | None = None


_SCAN_SORT_FIELDS = ('return_rate', 'sharpe_ratio', 'max_drawdown', 'win_rate', 'trade_count')


def _camel_to_snake(name: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


class ScanItemQueryModel(PaperBaseModel):
    page_num: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    status: Literal['pending', 'running', 'success', 'failed'] | None = None
    sort_by: str = Field(default='return_rate')
    order: Literal['asc', 'desc'] = 'desc'

    @field_validator('sort_by')
    @classmethod
    def validate_sort_by(cls, value: str) -> str:
        normalized = _camel_to_snake(value or '')
        if normalized not in _SCAN_SORT_FIELDS:
            raise ValueError(f'sort_by仅支持：{"、".join(_SCAN_SORT_FIELDS)}')
        return normalized


class ScanPickRequestModel(PaperBaseModel):
    batch_id: str = Field(min_length=1, max_length=36)
    codes: list[str] = Field(min_length=1, max_length=500)

    @field_validator('codes')
    @classmethod
    def validate_codes(cls, value: list[str]) -> list[str]:
        codes: list[str] = []
        for code in value:
            text = str(code or '').strip()
            if len(text) != _CODE_LENGTH or not text.isdigit():
                raise ValueError(f'股票代码无效：{code}')
            codes.append(text)
        return list(dict.fromkeys(codes))


# ---------------------------------------------------------------------------
# paper
# ---------------------------------------------------------------------------

class PaperAccountInitRequestModel(PaperBaseModel):
    account_name: str = Field(default='default', min_length=1, max_length=64)
    strategy_name: str = Field(min_length=1, max_length=64)
    initial_cash: int = Field(default=1_000_000, ge=1000, le=10_000_000_000)
    codes: list[str] = Field(default_factory=list, max_length=500)
    source_batch_id: str | None = None

    @field_validator('account_name', mode='before')
    @classmethod
    def normalize_account_name(cls, value: Any) -> Any:
        normalized = str(value or '').strip()
        return normalized or 'default'

    @field_validator('codes')
    @classmethod
    def validate_codes(cls, value: list[str]) -> list[str]:
        codes: list[str] = []
        for code in value:
            text = str(code or '').strip()
            if len(text) != _CODE_LENGTH or not text.isdigit():
                raise ValueError(f'股票代码无效：{code}')
            codes.append(text)
        return list(dict.fromkeys(codes))


class PaperAccountModel(PaperBaseModel):
    id: int
    account_name: str
    strategy_name: str | None = None
    initial_cash: int
    cash: float
    total_equity: float = 0
    position_value: float = 0
    return_rate: float = 0
    pnl: float = 0
    status: str


class PaperUniverseModel(PaperBaseModel):
    id: int
    account_id: int
    code: str
    name: str | None = None
    source_batch_id: str | None = None
    status: str


class PaperPositionModel(PaperBaseModel):
    id: int
    account_id: int
    code: str
    name: str | None = None
    quantity: int
    available_quantity: int
    avg_cost: float
    last_price: float | None = None
    market_value: float | None = None
    pnl: float | None = None


class PaperSignalModel(PaperBaseModel):
    id: int
    account_id: int
    code: str
    name: str | None = None
    signal_date: str
    signal: str
    reason: str | None = None
    close_price: float | None = None
    execute_date: str | None = None
    status: str


class PaperOrderModel(PaperBaseModel):
    id: int
    account_id: int
    code: str
    name: str | None = None
    signal_date: str | None = None
    execute_date: str
    side: str
    price: float | None = None
    quantity: int
    amount: float
    commission: float
    stamp_tax: float
    execute_status: str
    skip_reason: str | None = None


class PaperSnapshotModel(PaperBaseModel):
    id: int
    account_id: int
    date: str
    total_equity: float
    cash: float
    position_value: float
    pnl: float | None = None
    return_rate: float | None = None


class PaperPageQueryModel(PaperBaseModel):
    account_name: str = Field(default='default', max_length=64)
    page_num: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)
