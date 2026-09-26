"""
第一个QUANTAXIS程序
功能: 获取平安银行(000001)的历史数据
"""

import QUANTAXIS as QA
def main():
    # 获取股票日线数据
    # 参数: 股票代码, 开始日期, 结束日期
    df = QA.QA_fetch_get_stock_day(
        package='baostock',     
        code='000001',      # 平安银行
        start='2024-01-01', # 开始日期
        end='2024-01-31'    # 结束日期
    )

    # 显示数据
    print("\n" + "=" * 50)
    print("平安银行 2024年1月行情数据")
    print("=" * 50)
    print(df.head())
    print(df.columns.tolist())

    # 统计信息
    print("\n基本统计:")
    print(f"交易天数: {len(df)}")
    print(f"最高价: {df['high'].max():.2f}")
    print(f"最低价: {df['low'].min():.2f}")
    print(f"平均成交量: {df['volume'].mean():.0f}股")

if __name__ == '__main__':
    main()