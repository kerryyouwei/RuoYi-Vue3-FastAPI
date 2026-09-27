# -*- coding: utf-8 -*-
"""
方案A · 周频选基自动化（对应《ETF动量轮动操作手册》每周操作卡）

作用：运行一次即输出本周该不该动、买什么。
输出：
  1) 沪深300 的 MA20/MA60 与「是否弱市」
  2) 17 只 ETF 的 20 日涨幅排名 top3
  3) 双创增强信号（创业板ETF / 科创50ETF 相对沪深300 的超额）
  4) 与上次信号对比 → 给「换仓 / 不动」结论

数据源：腾讯行情 web.ifzq.gtimg.cn（东财 push2 接口会拦截本机 Python 的 TLS，腾讯可直连）
依赖：  pip install requests
运行：  python etf_rotation_weekly.py
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

try:
    import requests
except ImportError as e:
    sys.exit("缺少依赖：%s\n请先执行：pip install requests" % e)

# 直连腾讯行情，不走系统/环境代理（避免 Clash 未开时因代理而失败）
SESSION = requests.Session()
SESSION.trust_env = False

HERE = os.path.dirname(os.path.abspath(__file__))
LAST_FILE = os.path.join(HERE, "last_signal.json")

HS300 = "sh000300"
GEM_ETF = "159915"   # 创业板ETF
KCB_ETF = "588000"   # 科创50ETF
MOM_DAYS = 20
ROTATE_TOP1_GAIN = 0.05   # top1 20日涨幅 > 5% 才换仓
CYB_EDGE = 0.06           # 双创超额 ≥ 6% 才锁席
LIQ_MIN = 5e7             # 流动性硬门槛：日均成交额 ≥ 5000万
LIQ_MIN_SMALL = 3e7       # 3万小资金可放宽到 ≥ 3000万

ETF_POOL = {
    "510500": "中证500ETF",
    "159915": "创业板ETF",
    "588000": "科创50ETF",
    "512880": "证券ETF",
    "512800": "银行ETF",
    "512760": "芯片ETF",
    "512010": "医药ETF",
    "512660": "军工ETF",
    "159928": "消费ETF",
    "512690": "酒ETF",
    "515030": "新能车ETF",
    "515790": "光伏ETF",
    "512400": "有色ETF",
    "515220": "煤炭ETF",
    "512200": "地产ETF",
    "512980": "传媒ETF",
    "159998": "计算机ETF",
}

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _secid(code):
    """ETF 代码 → 腾讯市场前缀。5 开头沪(sh)，其余(15x/16x/18x)深(sz)。"""
    if code == "000300":
        return "sh000300"
    return ("sh" if code[0] == "5" else "sz") + code


def _kline(code, fq=False):
    """腾讯日线，fq=True 时前复权。返回行列表 [date, open, close, high, low, volume]。"""
    prefix = _secid(code)
    fqv = "qfq" if fq else ""
    param = "%s,day,,,320,%s" % (prefix, fqv)
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=" + param
    for _ in range(3):
        try:
            r = SESSION.get(url, headers=UA, timeout=15)
            j = r.json()
        except Exception:
            time.sleep(1)
            continue
        node = j.get("data", {}).get(prefix, {})
        for key in ("qfqday", "day"):
            arr = node.get(key)
            if isinstance(arr, list) and arr:
                return arr
        time.sleep(1)
    return None


def _to_close(arr):
    return [float(x[2]) for x in arr if len(x) >= 3] if arr else []


def _to_vol(arr):
    return [float(x[5]) for x in arr if len(x) >= 6] if arr else []


def ma(lst, n):
    return sum(lst[-n:]) / n if (lst is not None and len(lst) >= n) else None


def mom20(lst):
    return lst[-1] / lst[-1 - MOM_DAYS] - 1 if (lst is not None and len(lst) >= MOM_DAYS + 1) else None


def _avg_amount(closes, vols, days=20):
    """近似日均成交额(元)：腾讯 volume 单位≈手(1手=100股)，amount≈vol*100*close。"""
    if not vols or not closes:
        return None
    n = min(days, len(vols), len(closes))
    return sum(vols[-i] * 100 * closes[-i] for i in range(1, n + 1)) / n


def fmt_amount(amount):
    if amount is None:
        return "成交额未知"
    if amount >= 1e8:
        return "日均额%.2f亿" % (amount / 1e8)
    return "日均额%.0f万" % (amount / 1e4)


def liq_flag(amount):
    if amount is None:
        return ""
    if amount >= LIQ_MIN:
        return " ✅达标"
    if amount >= LIQ_MIN_SMALL:
        return " ⚠️仅3万户放宽"
    return " ❌不足"


def main():
    print("=" * 62)
    print("方案A 周频选基 · %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 62)

    idx_arr = _kline("000300", fq=False)
    idx = _to_close(idx_arr)
    if not idx or len(idx) < 61:
        sys.exit("沪深300数据不足，无法判断弱市，请检查网络后重试。")
    close = idx[-1]
    ma20v = ma(idx, 20)
    ma60v = ma(idx, 60)
    weak = (close < ma20v) and (ma20v < ma60v)
    hs_mom = mom20(idx)

    print("\n【铁律① 大市择时】")
    print("  沪深300 收盘%8.2f | MA20 %8.2f | MA60 %8.2f | 20日 %+.2f%%" % (close, ma20v, ma60v, (hs_mom or 0) * 100))
    if weak:
        print("  🔴 弱市（收盘<MA20 且 MA20<MA60）→ 清仓ETF，留黄金/国债/货基，本周收工，跳过选基。")
        payload = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "top1": None,
            "top3": [],
            "action": "弱市清仓",
        }
        with open(LAST_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("\n💰 弱市状态已保存到 %s；下周恢复非弱市后，将自动按新 top3 重新建仓。" % LAST_FILE)
        return
    print("  🟢 非弱市 → 继续选基。")

    print("\n【铁律② 动量选基】正在拉取各 ETF 20 日涨幅…")
    rows = {}
    amounts = {}
    for code, name in ETF_POOL.items():
        arr = _kline(code, fq=True)
        closes = _to_close(arr)
        m = mom20(closes)
        if m is None:
            print("  ⚠️ 跳过 %s %s（数据不足）" % (code, name))
            continue
        rows[code] = m
        amounts[code] = _avg_amount(closes, _to_vol(arr))
        time.sleep(0.2)

    if not rows:
        sys.exit("无任何ETF数据，请检查网络。")

    ranking = sorted(rows.items(), key=lambda kv: kv[1], reverse=True)
    top3 = ranking[:3]
    print("  —— 20日涨幅完整排名 ——")
    for i, (code, m) in enumerate(ranking, 1):
        name = ETF_POOL[code]
        amt = amounts.get(code)
        liq = fmt_amount(amt) + liq_flag(amt)
        print("   %2d. %s %-8s %+6.2f%%  %s" % (i, code, name, m * 100, liq))

    print("\n【铁律③ 换仓门槛】")
    top1_code, top1_m = top3[0]
    last = {}
    if os.path.exists(LAST_FILE):
        try:
            with open(LAST_FILE, encoding="utf-8") as f:
                last = json.load(f)
        except Exception:
            last = {}
    last_top1 = last.get("top1")
    print("  本轮 top1 = %s %s（%+.2f%%）" % (top1_code, ETF_POOL[top1_code], top1_m * 100))
    if last_top1 is None:
        print("  🟢 首次运行 / 上周弱市清仓 / 无历史记录 → 按本轮 top3 建仓。")
        action = "建仓 top3"
    elif last_top1 == top1_code:
        print("  ⚪ top1 未变 → 本周不动。")
        action = "不动"
    elif top1_m <= ROTATE_TOP1_GAIN:
        print("  ⚪ top1 已换人但涨幅 %+.2f%% ≤ 5%% → 不动（防磨损）。" % (top1_m * 100))
        action = "不动"
    else:
        print("  🔄 top1 换人且涨幅 > 5%% → 换仓到新 top3。")
        action = "换仓 top3"

    print("\n【铁律④ 双创增强（可选）】")
    if hs_mom is None:
        print("  基准数据不足，跳过。")
    else:
        for code, label in ((GEM_ETF, "创业板ETF"), (KCB_ETF, "科创50ETF")):
            m = rows.get(code)
            if m is None:
                print("  %s 数据不足" % label)
                continue
            ex = m - hs_mom
            flag = "  ✅ 超额≥6%，可锁1席" if ex >= CYB_EDGE else ""
            print("  %s %s 20日 %+.2f%% | 超额沪深300 %+.2f%%%s" % (code, label, m * 100, ex * 100, flag))

    print("\n【本轮 top3 目标】")
    for code, m in top3:
        print("  ✅ %s %s（%+.2f%%）" % (code, ETF_POOL[code], m * 100))

    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "top1": top1_code,
        "top3": [c for c, _ in top3],
        "action": action,
    }
    with open(LAST_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("\n💰 本次信号已保存到 %s，下次运行自动对比 top1。" % LAST_FILE)


if __name__ == "__main__":
    main()