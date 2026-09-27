import pandas as pd
import QUANTAXIS as QA
from pymongo import UpdateOne


CODE = '002594'
START = '2025-01-31'
END = '2026-08-31'


# 1. 从 Baostock 在线获取
df = QA.QA_fetch_get_stock_day(
    'baostock',
    CODE,
    START,
    END
)

if df is None or df.empty:
    raise RuntimeError("未能从 Baostock 获取行情数据")


# 2. 转换成 QUANTAXIS MongoDB 使用的字段格式
mongo_df = df.copy()

if 'volume' in mongo_df.columns:
    mongo_df = mongo_df.rename(columns={'volume': 'vol'})

mongo_df['code'] = mongo_df['code'].astype(str)
mongo_df['date'] = mongo_df['date'].astype(str)

records = QA.QA_util_to_json_from_pandas(
    mongo_df.reset_index(drop=True)
)


# 3. 写入 quantaxis.stock_day
collection = QA.DATABASE.stock_day

# 建立查询索引
collection.create_index([
    ('code', 1),
    ('date_stamp', 1)
])

# 使用 upsert，重复运行不会重复插入相同日期
operations = [
    UpdateOne(
        {
            'code': record['code'],
            'date_stamp': record['date_stamp']
        },
        {
            '$set': record
        },
        upsert=True
    )
    for record in records
]

if operations:
    result = collection.bulk_write(operations, ordered=False)
    print(
        f"MongoDB 写入完成："
        f"新增 {result.upserted_count} 条，"
        f"更新 {result.modified_count} 条"
    )


# 4. 从本地 MongoDB 重新读取
data = QA.QA_fetch_stock_day_adv(
    CODE,
    START,
    END
)

if data is None:
    raise RuntimeError("MongoDB 中没有查询到行情数据")

print(data.data.head())
print(f"本地数据数量：{len(data.data)}")