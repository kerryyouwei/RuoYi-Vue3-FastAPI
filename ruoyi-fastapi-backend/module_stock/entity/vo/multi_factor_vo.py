from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class MultiFactorBaseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, str_strip_whitespace=True)


class MultiFactorCalcRequestModel(MultiFactorBaseModel):
    """触发多因子计算请求。"""

    pass


class MultiFactorCalcResultModel(MultiFactorBaseModel):
    """多因子计算结果摘要。"""

    batch_id: str = Field(description='批次ID')
    total_count: int = Field(default=0, ge=0, description='参与计算股票总数')
    selected_count: int = Field(default=0, ge=0, description='入选股票数(>=90分)')
    degraded_factors: list[str] = Field(default_factory=list, description='降级因子列表')
    calc_date: date | None = Field(default=None, description='计算日期')
    elapsed_seconds: float = Field(default=0, ge=0, description='计算耗时(秒)')


class MultiFactorResultModel(MultiFactorBaseModel):
    """单条多因子选股结果。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    id: int
    batch_id: str
    code: str
    name: str | None = None
    total_score: float
    roe_score: float | None = None
    peg_score: float | None = None
    profit_growth_score: float | None = None
    volume_score: float | None = None
    macd_score: float | None = None
    northbound_score: float | None = None
    industry_score: float | None = None
    roe_value: float | None = None
    peg_value: float | None = None
    profit_growth_value: float | None = None
    turnover_rate_value: float | None = None
    macd_signal: str | None = None
    northbound_net: float | None = None
    industry_name: str | None = None
    industry_growth: float | None = None
    selected: int = 0
    factor_degraded: str | None = None
    calc_date: date | None = None
    create_time: datetime | None = None


class MultiFactorResultQueryModel(MultiFactorBaseModel):
    """多因子结果查询条件。"""

    batch_id: str | None = Field(default=None, max_length=32, description='批次ID，不传则查最新')
    selected_only: bool = Field(default=True, description='是否只显示入选股票')
    keyword: str | None = Field(default=None, max_length=100, description='代码或名称关键词')
    page_num: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class MultiFactorBatchInfoModel(MultiFactorBaseModel):
    """最新批次信息。"""

    batch_id: str = Field(description='批次ID')
    calc_date: date | None = Field(default=None, description='计算日期')
    total_count: int = Field(default=0, ge=0, description='参与计算股票总数')
    selected_count: int = Field(default=0, ge=0, description='入选股票数')
    degraded_factors: list[str] = Field(default_factory=list, description='降级因子列表')


class MultiFactorPoolAddRequestModel(MultiFactorBaseModel):
    """将多因子选股结果加入股票池请求。"""

    pool_name: str = Field(default='default', min_length=1, max_length=64, description='股票池名称')
    batch_id: str | None = Field(default=None, max_length=32, description='批次ID，不传则用最新')

    class Config:
        alias_generator = to_camel
        populate_by_name = True


class MultiFactorPoolAddResultModel(MultiFactorBaseModel):
    """加入股票池结果。"""

    pool_name: str
    requested_count: int = Field(default=0, ge=0)
    added_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)


class MultiFactorFactorWeightModel(MultiFactorBaseModel):
    """因子权重展示。"""

    factor_name: str = Field(description='因子名称')
    factor_label: str = Field(description='因子中文标签')
    weight: float = Field(description='权重百分比')
    enabled: bool = Field(default=True, description='是否启用')
