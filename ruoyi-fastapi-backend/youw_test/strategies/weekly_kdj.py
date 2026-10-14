"""周线 KDJ 中级趋势策略（完善版）。

将日线行情在策略内部重新合成为周线，计算周线 KDJ、EMA 趋势线与 ADX。
开仓：趋势向上 + ADX 未进入强趋势区 + 周线 KDJ 在超卖区金叉（可要求 J 双底共振）。
离场：周线 KDJ 高位死叉（可要求 J 双头共振）、周线趋势转空，以及
固定止损、跌破信号周低点、持仓时间止损。仅做多（系统中无做空接口）。
"""

import bisect

import backtrader as bt

from .base import BaseStrategy

DISPLAY_NAME = "周线KDJ趋势策略"
CATEGORY = "技术指标"
DESCRIPTION = "日线重采样为周线：KDJ金叉(J双底)+EMA/ADX过滤开仓，死叉/止损离场的中线波段策略。"


def _week_key(day):
    iso = day.isocalendar()
    return (iso[0], iso[1])


def build_weekly(opens, highs, lows, closes, day_dates):
    """把日线序列合成周线，返回周开/高/低/收及每根周线对应的最后一根日K下标。"""
    wo, wh, wl, wc, wend = [], [], [], [], []
    cur = None
    for i, day in enumerate(day_dates):
        key = _week_key(day)
        if cur is None or key != cur[0]:
            if cur is not None:
                wo.append(cur[1])
                wh.append(cur[2])
                wl.append(cur[3])
                wc.append(cur[4])
                wend.append(cur[5])
            cur = (key, opens[i], highs[i], lows[i], closes[i], i)
        else:
            cur = (key, cur[1], max(cur[2], highs[i]), min(cur[3], lows[i]), closes[i], i)
    if cur is not None:
        wo.append(cur[1])
        wh.append(cur[2])
        wl.append(cur[3])
        wc.append(cur[4])
        wend.append(cur[5])
    return wo, wh, wl, wc, wend


def compute_kdj(highs, lows, closes, n, m1, m2):
    """标准 KDJ，初始 K=D=50。"""
    k_vals, d_vals, j_vals = [], [], []
    prev_k, prev_d = 50.0, 50.0
    for i in range(len(closes)):
        lo = min(lows[max(0, i - n + 1): i + 1])
        hi = max(highs[max(0, i - n + 1): i + 1])
        rsv = 0.0 if hi <= lo else (closes[i] - lo) / (hi - lo) * 100.0
        k = (m1 - 1) / m1 * prev_k + 1.0 / m1 * rsv
        d = (m2 - 1) / m2 * prev_d + 1.0 / m2 * k
        j = 3.0 * k - 2.0 * d
        k_vals.append(k)
        d_vals.append(d)
        j_vals.append(j)
        prev_k, prev_d = k, d
    return k_vals, d_vals, j_vals


def compute_ema(values, period):
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * alpha + out[-1] * (1.0 - alpha))
    return out


def compute_adx(highs, lows, closes, period):
    """Wilder 平均趋向指数 ADX，有效前的窗口填 0。"""
    n = len(closes)
    adx = [0.0] * n
    if n < 2 * period:
        return adx
    tr = [0.0] * n
    pdm = [0.0] * n
    mdm = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm[i] = up if up > dn and up > 0 else 0.0
        mdm[i] = dn if dn > up and dn > 0 else 0.0
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = [0.0] * n
    spdm = [0.0] * n
    smdm = [0.0] * n
    atr[period] = sum(tr[1: period + 1])
    spdm[period] = sum(pdm[1: period + 1])
    smdm[period] = sum(mdm[1: period + 1])
    for i in range(period + 1, n):
        atr[i] = atr[i - 1] - atr[i - 1] / period + tr[i]
        spdm[i] = spdm[i - 1] - spdm[i - 1] / period + pdm[i]
        smdm[i] = smdm[i - 1] - smdm[i - 1] / period + mdm[i]
    dx = [0.0] * n
    for i in range(period, n):
        if atr[i] == 0:
            dx[i] = 0.0
            continue
        pdi = 100.0 * spdm[i] / atr[i]
        mdi = 100.0 * smdm[i] / atr[i]
        total = pdi + mdi
        dx[i] = 0.0 if total == 0 else 100.0 * abs(pdi - mdi) / total
    first = min(2 * period - 1, n - 1)
    adx[first] = sum(dx[period: first + 1]) / (first - period + 1)
    for i in range(first + 1, n):
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx


def _runs_below(values, threshold):
    """返回每个低于阈值区段的最低点：(最低点下标, 数值, 区段结束下标)。"""
    res, n, i = [], len(values), 0
    while i < n:
        if values[i] < threshold:
            start = i
            while i < n and values[i] < threshold:
                i += 1
            seg = values[start:i]
            m = min(seg)
            res.append((start + seg.index(m), m, i))
        else:
            i += 1
    return res


def _runs_above(values, threshold):
    res, n, i = [], len(values), 0
    while i < n:
        if values[i] > threshold:
            start = i
            while i < n and values[i] > threshold:
                i += 1
            seg = values[start:i]
            m = max(seg)
            res.append((start + seg.index(m), m, i))
        else:
            i += 1
    return res


class Strategy(BaseStrategy):
    params = (
        ("kdj_n", 9),
        ("kdj_m1", 3),
        ("kdj_m2", 3),
        ("ema_period", 20),
        ("adx_period", 14),
        ("j_oversold", 20),
        ("j_overbought", 90),
        ("k_buy_zone", 35),
        ("k_sell_zone", 65),
        ("adx_pause_threshold", 40),
        ("double_interval_min", 2),
        ("double_interval_max", 8),
        ("double_tolerance", 0.1),
        ("require_double_bottom", False),
        ("use_trend_exit", True),
        ("stop_loss", 0.08),
        ("use_week_low_stop", True),
        ("max_hold_weeks", 8),
        ("history_period", 120),
        ("max_trade_count", 0),
        ("trend_filter", True),
        ("all_in", True),
    )

    def __init__(self):
        super().__init__()
        n = len(self.data)
        opens = [float(x) for x in self.data.open.array]
        highs = [float(x) for x in self.data.high.array]
        lows = [float(x) for x in self.data.low.array]
        closes = [float(x) for x in self.data.close.array]
        days = [bt.num2date(x).date() for x in self.data.datetime.array]
        self.wo, self.wh, self.wl, self.wc, self.wend = build_weekly(opens, highs, lows, closes, days)
        self.K, self.D, self.J = compute_kdj(self.wh, self.wl, self.wc, self.p.kdj_n, self.p.kdj_m1, self.p.kdj_m2)
        self.ema = compute_ema(self.wc, self.p.ema_period)
        self.adx = compute_adx(self.wh, self.wl, self.wc, self.p.adx_period)
        self.week_count = len(self.wc)
        self.trend_bull = self._build_trend_state()
        self.ready_from = max(self.p.kdj_n, self.p.ema_period + 1, 2 * self.p.adx_period) + 2
        self._last_week = -1
        self._entry_week = None
        self._week_low_stop = None
        self.completed_buy_count = 0
        self.completed_sell_count = 0

    def _week_index(self, bar_index):
        return bisect.bisect_left(self.wend, bar_index)

    def _detect_double_bottom(self, wi):
        runs = _runs_below(self.J[: wi + 1], self.p.j_oversold)
        if len(runs) < 2:
            return False
        first, second = runs[-2], runs[-1]
        if second[2] > wi:
            return False
        gap = second[0] - first[0]
        if not (self.p.double_interval_min <= gap <= self.p.double_interval_max):
            return False
        return second[1] >= first[1] * (1.0 - self.p.double_tolerance)

    def _detect_double_top(self, wi):
        runs = _runs_above(self.J[: wi + 1], self.p.j_overbought)
        if len(runs) < 2:
            return False
        first, second = runs[-2], runs[-1]
        if second[2] > wi:
            return False
        gap = second[0] - first[0]
        if not (self.p.double_interval_min <= gap <= self.p.double_interval_max):
            return False
        return second[1] <= first[1] * (1.0 + self.p.double_tolerance)

    def _golden_cross(self, wi):
        return self.K[wi - 1] <= self.D[wi - 1] and self.K[wi] > self.D[wi]

    def _death_cross(self, wi):
        return self.K[wi - 1] >= self.D[wi - 1] and self.K[wi] < self.D[wi]

    def _build_trend_state(self):
        """带迟滞的周线趋势状态：EMA走多且价格站上EMA转多，EMA走空且价格跌破EMA转空，其余保持。"""
        n = self.week_count
        state = [False] * n
        for wi in range(1, n):
            up = self.ema[wi] > self.ema[wi - 1] and self.wc[wi] > self.ema[wi]
            down = self.wc[wi] < self.ema[wi] and self.ema[wi] < self.ema[wi - 1]
            if up:
                state[wi] = True
            elif down:
                state[wi] = False
            else:
                state[wi] = state[wi - 1]
        return state

    def _trend_up(self, wi):
        return self.trend_bull[wi]

    def _trend_down(self, wi):
        return not self.trend_bull[wi]

    def next(self):
        bar_index = len(self.data) - 1
        if not self.week_count:
            return
        wi = self._week_index(bar_index)
        if wi >= self.week_count:
            wi = self.week_count - 1
        self._check_exits(bar_index)
        if bar_index == self.wend[wi] and wi > self._last_week:
            self._last_week = wi
            if wi >= self.ready_from:
                self._evaluate_week(wi)

    def _check_exits(self, bar_index):
        if not self.position or self.pending_order is not None:
            return
        close = float(self.data.close[0])
        price = float(self.position.price)
        if price > 0 and close <= price * (1.0 - self.p.stop_loss):
            self.close_position("固定止损")
            return
        if self.p.use_week_low_stop and self._week_low_stop is not None and close < self._week_low_stop:
            self.close_position("跌破信号周低点")
            return
        if self._entry_week is not None:
            wi = self._week_index(bar_index)
            if wi - self._entry_week >= self.p.max_hold_weeks:
                self.close_position("时间止损")

    def _evaluate_week(self, wi):
        if self.position or self.pending_order is not None:
            self._evaluate_exits(wi)
        else:
            self._evaluate_entry(wi)

    def _evaluate_entry(self, wi):
        if self.p.max_trade_count and self.completed_buy_count >= self.p.max_trade_count:
            return
        if wi == 0:
            return
        golden = self._golden_cross(wi) and self.K[wi] <= self.p.k_buy_zone
        double = self._detect_double_bottom(wi)
        base_signal = golden and double if self.p.require_double_bottom else golden
        trend_ok = (not self.p.trend_filter) or self._trend_up(wi)
        adx_ok = self.adx[wi] < self.p.adx_pause_threshold
        if base_signal and trend_ok and adx_ok:
            self._entry_week = wi
            self._week_low_stop = min(self.wl[wi - 1], self.wl[wi])
            reason = "周线J双底+KDJ金叉" if self.p.require_double_bottom else "周线KDJ金叉"
            self.buy_position(reason + "(趋势向上)")
        else:
            self.signal = "持有"
            self.signal_reason = "等待买入信号"

    def _evaluate_exits(self, wi):
        if wi == 0 or not self.position:
            return
        death = self._death_cross(wi) and self.K[wi] >= self.p.k_sell_zone
        double_top = self._detect_double_top(wi)
        if death:
            self.close_position("周线J双头+KDJ死叉" if double_top else "周线KDJ高位死叉")
        elif self.p.use_trend_exit and self._trend_down(wi):
            self.close_position("周线趋势转空")
        else:
            self.signal = "持有"
            self.signal_reason = "持仓中"

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.completed_buy_count += 1
            else:
                self.completed_sell_count += 1
        super().notify_order(order)
