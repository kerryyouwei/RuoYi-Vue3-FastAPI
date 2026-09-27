"""腾讯行情 ETF 前复权日线加载器（回测引擎与冒烟测试共用）。

腾讯 fqkline 接口单次最多返回 640 根K线（实测 641+ 返回 param error），
因此按「结束日期向前翻页」方式补齐任意时间跨度，逐页去重。
"""

import time

_TENCENT_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
_PAGE_SIZE = 640
_MAX_PAGES = 12  # 12 * 640 ≈ 7680 根，覆盖约 30 年日线
_UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# 平台主时钟/基准可能使用沪深300等指数；腾讯也支持这些代码的日线。
_INDEX_SH_CODES = {'000300', '000905', '000852'}
_INDEX_SZ_CODES = {'399006', '399330'}


def _session():
    import requests

    session = requests.Session()
    session.trust_env = False  # 直连腾讯行情，避免本机代理未开导致失败
    return session


def _prefix(code: str) -> str:
    """ETF按市场前缀；常用指数按腾讯的 sh/sz 规则映射。"""
    if code in _INDEX_SH_CODES:
        return 'sh' + code
    if code in _INDEX_SZ_CODES:
        return 'sz' + code
    return ('sh' if code[0] in '569' else 'sz') + code


def _fetch_page(session, prefix: str, end: str, count: int, fq: str):
    """取一页K线（升序），失败重试3次；无数据返回 None。"""
    if end:
        param = f'{prefix},day,,{end},{count},{fq}'
    else:
        param = f'{prefix},day,,,{count},{fq}'
    last_error = None
    for _ in range(3):
        try:
            response = session.get(f'{_TENCENT_URL}?param={param}', headers=_UA, timeout=15)
            payload = response.json()
        except Exception as exc:  # 网络抖动重试
            last_error = exc
            time.sleep(0.5)
            continue
        node = payload.get('data')
        if not isinstance(node, dict):
            return None  # param error / 无该标的
        rows = node.get(prefix)
        if isinstance(rows, dict):
            for key in ('qfqday', 'day'):
                arr = rows.get(key)
                if isinstance(arr, list) and arr:
                    return arr
        return None
    raise RuntimeError(f'腾讯行情请求失败: {last_error}')


def fetch_etf_daily(code: str, start: str, end: str):
    """返回 DataFrame(datetime 索引, open/high/low/close/volume)，无数据返回 None。"""
    import pandas as pd

    prefix = _prefix(code)
    start_s = str(start)[:10]
    end_s = str(end)[:10]
    session = _session()
    by_date = {}
    cursor = end_s
    for _ in range(_MAX_PAGES):
        arr = _fetch_page(session, prefix, cursor, _PAGE_SIZE, 'qfq')
        if not arr:
            break
        first_day = str(arr[0][0])[:10]
        fresh = 0
        for row in arr:
            if len(row) < 6:
                continue
            day = str(row[0])[:10]
            if day in by_date:
                continue
            try:
                # 腾讯行结构: [date, open, close, high, low, volume]
                by_date[day] = (
                    float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]),
                )
            except (TypeError, ValueError):
                continue
            fresh += 1
        if fresh == 0 or first_day <= start_s:
            break
        cursor = first_day
    if not by_date:
        return None
    days = sorted(day for day in by_date if start_s <= day <= end_s)
    if not days:
        return None
    frame = pd.DataFrame(
        [by_date[day] for day in days],
        index=pd.to_datetime(days),
        columns=['open', 'close', 'high', 'low', 'volume'],
    )
    return frame[['open', 'high', 'low', 'close', 'volume']].sort_index()