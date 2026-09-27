from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class StockListQueryModel(BaseModel):
    """
    股票列表分页查询参数模型
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, str_strip_whitespace=True)

    code: str | None = Field(default=None, max_length=20, description='股票代码')
    name: str | None = Field(default=None, max_length=50, description='股票名称')
    sse: str | None = Field(default=None, max_length=2, description='市场：sh上海，sz深圳')
    page_num: int = Field(default=1, ge=1, description='当前页码')
    page_size: int = Field(default=10, ge=1, le=100, description='每页记录数')


class StockListModel(BaseModel):
    """
    股票列表数据模型
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    code: str = Field(description='股票代码')
    name: str = Field(description='股票名称')
    sse: str = Field(description='市场：sh上海，sz深圳')
    ipo_date: str | None = Field(default=None, description='上市日期')
    out_date: str | None = Field(default=None, description='退市日期')
    status: str = Field(description='状态：1上市，0退市')


class StockListImportResultModel(BaseModel):
    """
    股票列表导入结果模型
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    fetched_count: int = Field(description='获取数据条数')
    inserted_count: int = Field(description='新增数据条数')
    updated_count: int = Field(description='更新数据条数')
    message: str = Field(description='导入提示信息')


