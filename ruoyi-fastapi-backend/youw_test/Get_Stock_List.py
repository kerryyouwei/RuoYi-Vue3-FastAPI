"""
QUANTAXIS 示例程序
功能: 获取所有股票列表
参考: Hello_QUANTAXIS.py
"""

import QUANTAXIS as QA


def main():
    # 获取股票列表
    # 参数: package 指定数据源, 这里使用 baostock
    df = QA.QA_fetch_get_stock_list(
        package='baostock'
    )

    # 显示股票列表
    print("\n" + "=" * 50)
    print("A股股票列表")
    print("=" * 50)
    print(df.head(20))
    print("\n字段:", df.columns.tolist())

    # 统计信息
    print("\n基本统计:")
    print(f"股票总数: {len(df)}")
    if not df.empty:
        # sse 字段: sh=上海, sz=深圳
        market_count = df['sse'].value_counts()
        for market, count in market_count.items():
            print(f"{market} 数量: {count}")


if __name__ == '__main__':
    main()
