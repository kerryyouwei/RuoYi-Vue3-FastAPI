"""
从 QUANTAXIS 使用的 MongoDB 获取比亚迪（002594）日线数据。
"""

import QUANTAXIS as QA


CODE = "002594"
START = "2025-01-01"
END = "2026-03-31"


def main():
    # QA_fetch_stock_day_adv 默认从 quantaxis.stock_day 集合读取数据。
    data = QA.QA_fetch_stock_day_adv(CODE, START, END)

    if data is None or data.data.empty:
        raise RuntimeError(
            f"MongoDB 中没有找到 {CODE} 在 {START} 至 {END} 的日线数据"
        )

    df = data.data

    print("\n" + "=" * 50)
    print(f"比亚迪（{CODE}）{START} 至 {END} 日线数据")
    print("=" * 50)
    print(df.head(100))
    print(f"\n数据字段: {df.columns.tolist()}")

    print("\n基本统计:")
    print(f"交易天数: {len(df)}")
    print(f"最高价: {df['high'].max():.2f}")
    print(f"最低价: {df['low'].min():.2f}")
    print(f"平均成交量: {df['volume'].mean():.0f}股")


if __name__ == "__main__":
    main()
