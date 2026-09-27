# -*- coding: utf-8 -*-
"""
方案A · ETF动量轮动（3–5万版）—— 聚宽回测策略
================================================
对应《方案A_ETF动量轮动_3-5万实盘操作手册.md》六条铁律的自动实现：

  铁律① 大市择时   沪深300 收盘<MA20 且 MA20<MA60 → 弱市，清仓所有ETF
  铁律② 动量选基   池内ETF按20日涨幅排序取 top N（3只起步，翻倍升5只）
  铁律③ 换仓门槛   top1 换人 且 20日涨幅>5% 才换仓，否则本周不动
  铁律④ 双创增强   创业板/科创50 20日超额沪深300 ≥ 6% → 锁1席给更强者
  铁律⑤ 止损冷却   单只距买入价 -8% 止损；卖出后20个交易日冷却
  铁律⑥ 仓位分档   资金<2×起步→3只，2~4×→5只，4~8×→6只，≥8×→8只

【回测设置】
  平台：聚宽 JoinQuant → 新建策略 → 粘贴本文件全部内容
  基准：沪深300（000300.XSHG，代码内已 set_benchmark）
  频率：每天（天）；初始资金：50000
  时间：建议 2021-01-01 ~ 至今（2021年后标的池基本齐全；
        更早年份池子不全，代码会自动跳过未上市/数据不足的标的）
  成本：基金佣金万3、最低5元、免印花税（代码内已设置）

【验证要点】（跑完后对照回测日志逐条检查）
  1. 弱市区间应出现“🔴 弱市 → 清仓”，且期间持仓为空
  2. 常规周调仓仅在 top1 换人且20日涨幅>5% 时发生，其余打印“⚪ 本周不动”
  3. 止损日志出现“🛑”，且该ETF随后20个交易日内不再被买入（冷却生效）
  4. 双创超额≥6%的时段出现“🚀 双创通道锁席”
  5. 收益曲线应明显跑赢/回撤小于 沪深300 基准（弱市空仓的体现）
"""
from jqdata import *

# 标的池（与手册第2节一致；宽基准 510300 只作比较不买卖）
POOL = [
    ('510500.XSHG', '中证500ETF'),
    ('159915.XSHE', '创业板ETF'),
    ('588000.XSHG', '科创50ETF'),
    ('512880.XSHG', '证券ETF'),
    ('512800.XSHG', '银行ETF'),
    ('512760.XSHG', '芯片ETF'),
    ('512010.XSHG', '医药ETF'),
    ('512660.XSHG', '军工ETF'),
    ('159928.XSHE', '消费ETF'),
    ('512690.XSHG', '酒ETF'),
    ('515030.XSHG', '新能车ETF'),
    ('515790.XSHG', '光伏ETF'),
    ('512400.XSHG', '有色ETF'),
    ('515220.XSHG', '煤炭ETF'),
    ('512200.XSHG', '地产ETF'),
    ('512980.XSHG', '传媒ETF'),
    ('159998.XSHE', '计算机ETF'),
]
HS300 = '000300.XSHG'
GEM_ETF = '159915.XSHE'   # 创业板ETF
KCB_ETF = '588000.XSHG'   # 科创50ETF


def initialize(context):
    set_benchmark(HS300)
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    # 手册：ETF免印花税，佣金万3、最低5元
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0003,
                             close_commission=0.0003, close_today_commission=0,
                             min_commission=5), type='fund')
    log.set_level('order', 'error')

    # ---- 参数（与手册一致，可调）----
    g.mom_days = 20        # 20日动量
    g.rotate_gain = 0.05   # 铁律③ top1 涨幅>5% 才换仓
    g.cyb_edge = 0.06      # 铁律④ 双创超额≥6% 锁席
    g.stop_ratio = 0.92    # 铁律⑤ -8% 止损（激进取0.90）
    g.cooldown_days = 20   # 铁律⑤ 卖出后冷却20个交易日
    g.last_top1 = None     # 上次调仓的 top1（用于铁律③对比）
    g.cooldown = {}        # {code: 卖出日期} 冷却登记

    run_weekly(rebalance, 1, '10:00')   # 每周一调仓检查（对应手册每周日复盘）
    run_daily(stop_loss, '14:00')       # 每日止损检查


def calc_hold_num(context):
    """铁律⑥：按 总资产/起步资金 分档，任何初始资金行为一致。"""
    base = context.portfolio.starting_cash or 50000.0
    if base <= 0:
        base = 50000.0
    multi = context.portfolio.total_value / base
    if multi < 2.0:
        return 3
    if multi < 4.0:
        return 5
    if multi < 8.0:
        return 6
    return 8


def close_series(context, code, count):
    df = get_price(code, end_date=context.previous_date, frequency='daily',
                   fields=['close'], count=count, skip_paused=True)
    s = df['close'].dropna()
    return s if len(s) >= count else None


def mom20(context, code):
    s = close_series(context, code, g.mom_days + 1)
    if s is None:
        return None
    return float(s.iloc[-1] / s.iloc[0] - 1)


def is_weak(context):
    """铁律①：沪深300 收盘<MA20 且 MA20<MA60 → 弱市。"""
    s = close_series(context, HS300, 61)
    if s is None:
        return False
    c = s.iloc[-1]
    ma20 = s.tail(20).mean()
    ma60 = s.tail(60).mean()
    return bool(c < ma20 and ma20 < ma60)


def in_cooldown(context, code):
    """铁律⑤：该ETF卖出后未满20个交易日 → True。"""
    d = g.cooldown.get(code)
    if d is None:
        return False
    try:
        td = get_trade_days(start_date=d, end_date=context.current_dt.date())
        return len(td) < g.cooldown_days
    except Exception:
        return True


def pick_channel(context, moms, mom300):
    """铁律④：双创超额≥6% → 返回超额更大者，否则 None。"""
    best = None
    for code, label in ((GEM_ETF, '创业板'), (KCB_ETF, '科创50')):
        m = moms.get(code)
        if m is None or mom300 is None:
            continue
        ex = m - mom300
        if ex >= g.cyb_edge and (best is None or ex > best[1]):
            best = (code, ex, label)
    if best:
        log.info('🚀 双创通道锁席：%s（20日超额沪深300 %+.1f%%）' % (best[2], best[1] * 100))
        return best[0]
    return None


def clear_all(context, reason):
    for p in list(context.portfolio.positions.values()):
        if p.total_amount > 0:
            order_target(p.security, 0)
    log.info('🔴 %s → 清仓所有ETF（弱市转黄金/国债/货基由人工执行，策略内空仓）' % reason)


def rebalance(context):
    n = calc_hold_num(context)
    log.info('==== 周调仓 %s | 目标持仓%d只 ====' % (context.current_dt.date(), n))

    # ---- 铁律① 大市择时 ----
    if is_weak(context):
        g.last_top1 = None
        clear_all(context, '弱市（沪深300 收盘<MA20 且 MA20<MA60）')
        return

    # ---- 铁律② 动量选基（自动跳过未上市/数据不足标的）----
    pool = []
    for code, name in POOL:
        try:
            info = get_security_info(code)
            if info is None or info.start_date > context.previous_date:
                continue
        except Exception:
            continue
        m = mom20(context, code)
        if m is not None:
            pool.append((m, code, name))
    if len(pool) < 3:
        log.info('⚠️ 可用标的不足3只（当前%d），跳过本次调仓' % len(pool))
        return
    pool.sort(reverse=True)
    ranking = [(c, nm, m) for m, c, nm in pool]
    top1_code, top1_name, top1_m = ranking[0]
    log.info('📊 动量前%d: %s' % (n, ' | '.join(
        '%s %+.1f%%' % (c.split('.')[0], m * 100) for c, _, m in ranking[:n])))

    # ---- 铁律④ 双创增强 ----
    target = [c for c, _, _ in ranking[:n]]
    ch = pick_channel(context, dict((c, m) for c, _, m in ranking), mom20(context, HS300))
    if ch and ch not in target:
        target = [ch] + target[:n - 1]

    # ---- 铁律⑤ 冷却过滤 ----
    blocked = [c for c in target if in_cooldown(context, c)]
    if blocked:
        log.info('🧊 冷却中跳过: %s' % ' '.join(blocked))
        target = [c for c in target if c not in blocked]
    if not target:
        log.info('⚠️ 目标全被冷却过滤，本周不动')
        return

    # ---- 铁律③ 换仓门槛 ----
    holdings = [p.security for p in context.portfolio.positions.values() if p.total_amount > 0]
    allow = (g.last_top1 is None) \
        or (top1_code != g.last_top1 and top1_m >= g.rotate_gain) \
        or (len(holdings) < len(target))
    if not allow:
        log.info('⚪ top1未变或涨幅不足（%s %+.1f%%）→ 本周不动' % (top1_name, top1_m * 100))
        return
    g.last_top1 = top1_code

    # ---- 执行：先卖旧，再等权买新 ----
    for code in holdings:
        if code not in target:
            log.info('📤 卖出 %s' % code)
            order_target(code, 0)
    to_buy = [c for c in target if c not in holdings]
    if to_buy:
        per = context.portfolio.total_value * 0.95 / len(target)
        for code in to_buy:
            order_target_value(code, per)
            log.info('📥 买入 %s 目标市值%.0f' % (code, per))


def stop_loss(context):
    """铁律⑤：每日14:00检查，-8%止损并登记20个交易日冷却。"""
    for p in list(context.portfolio.positions.values()):
        code = p.security
        if p.total_amount <= 0 or not p.avg_cost:
            continue
        if p.price < p.avg_cost * g.stop_ratio:
            order_target(code, 0)
            g.cooldown[code] = context.current_dt.date()
            log.info('🛑 止损 %s（成本%.3f 现价%.3f，盈亏%+.1f%%）→ 冷却%d个交易日'
                     % (code, p.avg_cost, p.price, (p.price / p.avg_cost - 1) * 100, g.cooldown_days))