# -*- coding: utf-8 -*-
"""
方案A · 持仓止损监控自动化（对应《ETF动量轮动操作手册》每日检查卡）

作用：读 holdings.json，拉最新收盘价，输出每只持仓的盈亏与 -8% 止损状态。

数据源：腾讯行情 web.ifzq.gtimg.cn（东财 push2 接口会拦截本机 Python 的 TLS，腾讯可直连）
依赖：  pip install requests
运行：  python etf_stop_monitor.py
首次运行即生成 holdings.json 模板（无需联网），填好真实持仓后重新运行。
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
HOLDINGS_FILE = os.path.join(HERE, "holdings.json")
STOP_RATIO = 0.92   # -8% 止损线
WARN_RATIO = 0.94   # -6% 预警线

TEMPLATE = {
    "_说明": "code=ETF代码, name=名称, buy_price=买入均价, shares=持有份额, buy_date=买入日期。填写后保存并重新运行本脚本。",
    "positions": [
        {"code": "512760", "name": "芯片ETF", "buy_price": 1.02, "shares": 9300, "buy_date": "2026-01-05"},
    ],
}

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def load():
    if not os.path.exists(HOLDINGS_FILE):
        with open(HOLDINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(TEMPLATE, f, ensure_ascii=False, indent=2)
        print("✅ 已生成模板 %s\n   请按实际情况填写 positions（保留或删除示例），然后重新运行。" % HOLDINGS_FILE)
        sys.exit(0)
    with open(HOLDINGS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _secid(code):
    return ("sh" if code[0] == "5" else "sz") + code


def latest_close(sess, code):
    prefix = _secid(code)
    param = "%s,day,,,40,qfq" % prefix
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=" + param
    for _ in range(3):
        try:
            r = sess.get(url, headers=UA, timeout=15)
            j = r.json()
        except Exception:
            time.sleep(1)
            continue
        node = j.get("data", {}).get(prefix, {})
        for key in ("qfqday", "day"):
            arr = node.get(key)
            if isinstance(arr, list) and arr:
                return float(arr[-1][2])
        time.sleep(1)
    return None


def main():
    data = load()
    pos = data.get("positions", [])
    if not pos:
        print("holdings.json 的 positions 为空，请先填写持仓。")
        return

    try:
        import requests
    except ImportError as e:
        sys.exit("缺少依赖：%s\n请先执行：pip install requests" % e)

    SESSION = requests.Session()
    SESSION.trust_env = False

    print("=" * 64)
    print("方案A 止损监控 · %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("止损线 -8%（价×0.92） | 预警线 -6%（价×0.94）")
    print("=" * 64)
    print("%-8s %-8s %8s %8s %8s %8s %s" % ("代码", "名称", "现价", "买入价", "盈亏%", "止损价", "状态"))

    actions = []
    for p in pos:
        code = p.get("code")
        name = p.get("name", "")
        try:
            bp = float(p.get("buy_price"))
        except (TypeError, ValueError):
            bp = 0.0
        if not code or bp <= 0:
            continue
        c = latest_close(SESSION, code)
        if c is None:
            print("%-8s %-8s  数据获取失败，跳过" % (code, name))
            continue
        pnl = (c / bp - 1) * 100
        stop = bp * STOP_RATIO
        if c <= stop:
            st = "🔴 触发止损"
            actions.append("卖出 %s %s（现价 %.3f ≤ 止损价 %.3f）" % (code, name, c, stop))
        elif c <= bp * WARN_RATIO:
            st = "🟡 预警≤-6%"
            actions.append("盯紧 %s %s（盈亏 %+.1f%%，止损价 %.3f）" % (code, name, pnl, stop))
        else:
            st = "🟢 正常"
        print("%-8s %-8s %8.3f %8.3f %+7.1f %8.3f %s" % (code, name, c, bp, pnl, stop, st))
        time.sleep(0.2)

    print("-" * 64)
    if actions:
        print("今日执行建议：")
        for a in actions:
            print("  • " + a)
        print("\n卖出后请从 holdings.json 删除对应条目，并注意该板块 20 个交易日冷却。")
    else:
        print("今日无止损动作。按纪律：不做盘中追涨杀跌，收盘后确认即可。")


if __name__ == "__main__":
    main()