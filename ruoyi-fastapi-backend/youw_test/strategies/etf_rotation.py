"""方案A · ETF动量轮动（3–5万版）——本地 Backtrader 组合策略。

对应《方案A_ETF动量轮动_3-5万实盘操作手册.md》六条铁律：
  ① 沪深300 收盘<MA20 且 MA20<MA60 → 弱市清仓
  ② 20日动量排序取 top N（3只起步，翻倍升5只）
  ③ top1 换人且涨幅>5% 才换仓，否则本周不动
  ④ 创业板/科创50 20日超额沪深300 ≥ 6% → 锁1席
  ⑤ -8% 止损 + 20个交易日冷却
  ⑥ 仓位分档 <2x:3 / 2~4x:5 / 4~8x:6 / >=8x:8

平台回测请求建议：code=000300（主时钟+基准），初始资金 50000，
印花税率填 0（ETF 免印花税），时间建议 2021-01-01 起。
"""

import backtrader as bt

from .base import BaseStrategy

DISPLAY_NAME = '方案A · ETF动量轮动'
CATEGORY = 'rotation'
DESCRIPTION = '沪深300弱市清仓；17只ETF按20日动量轮动（top1换人且>5%才换仓）；双创超额≥6%锁1席；-8%止损+20交易日冷却'

UNIVERSE = [
    '510500', '159915', '588000', '512880', '512800', '512760', '512010',
    '512660', '159928', '512690', '515030', '515790', '512400', '515220',
    '512200', '512980', '159998',
]
GEM_ETF = '159915'   # 创业板ETF
KCB_ETF = '588000'   # 科创50ETF


class Strategy(BaseStrategy):
    # 引擎会读取策略类上的 UNIVERSE 来决定是否加载多只标的。
    UNIVERSE = UNIVERSE

    params = (
        ('mom_period', 20),
        ('regime_ma_period', 60),
        ('rotate_gain', 0.05),
        ('cyb_edge', 0.06),
        ('stop_ratio', 0.92),
        ('cooldown_days', 20),
    )

    def __init__(self):
        super().__init__()
        self._universe_set = set(UNIVERSE)
        self._data_by_name = {d._name: d for d in self.datas if d._name in self._universe_set}
        self._last_top1 = None
        self._cooldown = {}          # code -> 卖出时的 bar 序号
        self._bar_no = 0             # 主时钟 bar 计数（1 bar ≈ 1 交易日）
        self._last_rebalance = None

    # ---------- 基础工具 ----------

    def _universe_datas(self):
        return [self._data_by_name[name] for name in self._data_by_name]

    def _mom(self, data, period):
        closes = data.close.get(size=period + 1)
        if closes is None or len(closes) < period + 1 or closes[0] <= 0:
            return None
        return closes[-1] / closes[0] - 1

    def _is_weak(self):
        """铁律①：主时钟(沪深300) 收盘<MA20 且 MA20<MA60。"""
        closes = self.datas[0].close.get(size=self.p.regime_ma_period)
        if closes is None or len(closes) < self.p.regime_ma_period:
            return False
        ma_short = sum(closes[-20:]) / 20
        ma_long = sum(closes) / len(closes)
        return closes[-1] < ma_short and ma_short < ma_long

    def _hold_num(self):
        """铁律⑥：按 总资产/起步资金 分档。"""
        base = float(self.broker.startingcash or 50000.0) or 50000.0
        multi = float(self.broker.getvalue()) / base
        if multi < 2.0:
            return 3
        if multi < 4.0:
            return 5
        if multi < 8.0:
            return 6
        return 8

    def _in_cooldown(self, code):
        sold_bar = self._cooldown.get(code)
        return sold_bar is not None and (self._bar_no - sold_bar) < self.p.cooldown_days

    def _lots(self, data, value):
        """按手(100份)取整，并保证含佣金不超过可用现金。"""
        price = float(data.close[0])
        if price <= 0:
            return 0
        cash = float(self.broker.getcash())
        size = int(min(value, cash) / price // 100 * 100)
        info = self.broker.getcommissioninfo(data)
        while size > 0:
            cost = size * price + info.getcommission(size, price)
            if cost <= cash:
                break
            size -= 100
        return size

    def _pick_channel(self, moms, mom_master):
        """铁律④：双创超额≥阈值 → 返回超额更大者。"""
        if mom_master is None:
            return None
        best = None
        for code in (GEM_ETF, KCB_ETF):
            m = moms.get(code)
            if m is None:
                continue
            ex = m - mom_master
            if ex >= self.p.cyb_edge and (best is None or ex > best[1]):
                best = (code, ex)
        return best[0] if best else None

    # ---------- 主流程 ----------

    def next(self):
        master_date = self.datas[0].datetime.date(0)
        self._bar_no += 1
        due = (
            self._last_rebalance is None
            or master_date.weekday() == 0
            or (master_date - self._last_rebalance).days >= 7
        )
        if due:
            self._last_rebalance = master_date
            self._rebalance(master_date)
        self._check_stop_loss()

    def _rebalance(self, master_date):
        n = self._hold_num()
        self.log(f'==== 周调仓 {master_date} | 目标持仓{n}只 ====')

        # 铁律① 大市择时
        if self._is_weak():
            self._last_top1 = None
            for data in self._universe_datas():
                if self.getposition(data).size > 0:
                    self.order_target_size(data=data, target=0)
            self.log('🔴 弱市（沪深300 收盘<MA20 且 MA20<MA60）→ 清仓所有ETF')
            return

        # 铁律② 动量选基
        moms = {}
        for data in self._universe_datas():
            if data.datetime.date(0) != master_date:
                continue  # 未上市/当日无bar
            m = self._mom(data, self.p.mom_period)
            if m is not None:
                moms[data._name] = m
        if len(moms) < 3:
            self.log(f'⚠️ 可用标的不足3只({len(moms)})，跳过本次调仓')
            return
        ranking = sorted(moms.items(), key=lambda kv: kv[1], reverse=True)
        top1_code, top1_m = ranking[0]
        self.log('📊 动量前%d: %s' % (n, ' | '.join('%s %+.1f%%' % (c, m * 100) for c, m in ranking[:n])))

        target = [c for c, _ in ranking[:n]]

        # 铁律④ 双创增强
        channel = self._pick_channel(moms, self._mom(self.datas[0], self.p.mom_period))
        if channel and channel not in target:
            target = [channel] + target[:n - 1]
            self.log(f'🚀 双创通道锁席: {channel}')

        # 铁律⑤ 冷却过滤
        blocked = [c for c in target if self._in_cooldown(c)]
        if blocked:
            self.log('🧊 冷却中跳过: %s' % ' '.join(blocked))
            target = [c for c in target if c not in blocked]
        if not target:
            self.log('⚠️ 目标全在冷却，本周不动')
            return

        # 铁律③ 换仓门槛
        holdings = [name for name, data in self._data_by_name.items() if self.getposition(data).size > 0]
        allow = (
            self._last_top1 is None
            or (top1_code != self._last_top1 and top1_m > self.p.rotate_gain)
            or len(holdings) < len(target)
        )
        if not allow:
            self.log('⚪ top1未变或涨幅不足（%s %+.1f%%）→ 本周不动' % (top1_code, top1_m * 100))
            return
        self._last_top1 = top1_code

        # 执行：先卖旧，再等权买新
        for name, data in self._data_by_name.items():
            if self.getposition(data).size > 0 and name not in target:
                self.log(f'📤 卖出 {name}')
                self.order_target_size(data=data, target=0)
        to_buy = [c for c in target if c not in holdings]
        if to_buy:
            per_seat = float(self.broker.getvalue()) * 0.95 / len(target)
            for code in to_buy:
                data = self._data_by_name[code]
                size = self._lots(data, per_seat)
                if size > 0:
                    self.buy(data=data, size=size)
                    self.log(f'📥 买入 {code} {size}份 目标市值≈{per_seat:.0f}')

    def _check_stop_loss(self):
        """铁律⑤：每日检查，-8% 止损并登记冷却。"""
        for name, data in self._data_by_name.items():
            pos = self.getposition(data)
            if pos.size <= 0 or not pos.price:
                continue
            if float(data.close[0]) < float(pos.price) * self.p.stop_ratio:
                self.order_target_size(data=data, target=0)
                self._cooldown[name] = self._bar_no
                self.log(
                    '🛑 止损 %s（成本%.3f 现价%.3f，盈亏%+.1f%%）→ 冷却%d个交易日'
                    % (name, pos.price, data.close[0], (data.close[0] / pos.price - 1) * 100, self.p.cooldown_days)
                )