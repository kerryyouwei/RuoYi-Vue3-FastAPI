"""股票池动量轮动 —— 多因子股票池组合策略。

对应《股票池筛选 + 回测：详细执行思路》第一版组合层策略：
  ① 沪深300 收盘<MA20 且 MA20<MA60 → 弱市清仓
  ② 池内股票按 20 日动量排序取 top N
  ③ top1 换人且涨幅>5% 才换仓，否则本周不动（防磨损）
  ④ -8% 止损 + 20 个交易日冷却
  ⑤ 等权分仓，目标持仓默认 5 只

标的池由回测引擎按 pool_codes 快照动态加载（datas[0]=沪深300主时钟，
datas[1:] 为股票池）；引擎会自动跳过无日线价格数据的股票。
"""

from datetime import date

import backtrader as bt

from .base import BaseStrategy

DISPLAY_NAME = '股票池动量轮动'
CATEGORY = 'rotation'
DESCRIPTION = '多因子股票池按20日动量topN等权轮动；沪深300弱市清仓；top1换人且>5%才换仓；-8%止损+20交易日冷却'
IS_PORTFOLIO = True
_REGIME_MA_SHORT = 20
_REBALANCE_MAX_GAP_DAYS = 7


class Strategy(BaseStrategy):
    params = (
        ('mom_period', 20),
        ('regime_ma_period', 60),
        ('top_n', 5),
        ('rotate_gain', 0.05),
        ('stop_ratio', 0.92),
        ('cooldown_days', 20),
    )

    def __init__(self) -> None:
        super().__init__()
        self._pool_datas = [d for d in self.datas[1:] if d._name != self.datas[0]._name]
        self._last_top1 = None
        self._cooldown = {}          # code -> 卖出时的 bar 序号
        self._bar_no = 0             # 主时钟 bar 计数（1 bar ≈ 1 交易日）
        self._last_rebalance = None

    # ---------- 基础工具 ----------

    def _mom(self, data: bt.DataBase, period: int) -> float | None:
        closes = data.close.get(size=period + 1)
        if closes is None or len(closes) < period + 1 or closes[0] <= 0:
            return None
        return closes[-1] / closes[0] - 1

    def _is_weak(self) -> bool:
        """铁律①：主时钟(沪深300) 收盘<MA20 且 MA20<MA60。"""
        closes = self.datas[0].close.get(size=self.p.regime_ma_period)
        if closes is None or len(closes) < self.p.regime_ma_period:
            return False
        ma_short = sum(closes[-_REGIME_MA_SHORT:]) / _REGIME_MA_SHORT
        ma_long = sum(closes) / len(closes)
        return closes[-1] < ma_short < ma_long

    def _in_cooldown(self, code: str) -> bool:
        sold_bar = self._cooldown.get(code)
        return sold_bar is not None and (self._bar_no - sold_bar) < self.p.cooldown_days

    def _lots(self, data: bt.DataBase, value: float) -> int:
        """按手(100股)取整，并保证含佣金不超过可用现金。"""
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

    # ---------- 主流程 ----------

    def next(self) -> None:
        master_date = self.datas[0].datetime.date(0)
        self._bar_no += 1
        due = (
            self._last_rebalance is None
            or master_date.weekday() == 0
            or (master_date - self._last_rebalance).days >= _REBALANCE_MAX_GAP_DAYS
        )
        if due:
            self._last_rebalance = master_date
            self._rebalance(master_date)
        self._check_stop_loss()

    def _rebalance(self, master_date: date) -> None:
        self.log(f'==== 周调仓 {master_date} | 目标持仓{self.p.top_n}只 ====')

        # 铁律① 大市择时
        if self._is_weak():
            self._last_top1 = None
            for data in self._pool_datas:
                if self.getposition(data).size > 0:
                    self.order_target_size(data=data, target=0)
            self.log('🔴 弱市（沪深300 收盘<MA20 且 MA20<MA60）→ 清仓股票池持仓')
            return

        # 铁律② 动量选股：只统计当日有 bar 的股票（停牌/未上市自动跳过）
        moms = {}
        for data in self._pool_datas:
            if data.datetime.date(0) != master_date:
                continue
            m = self._mom(data, self.p.mom_period)
            if m is not None:
                moms[data._name] = m
        if not moms:
            self.log('⚠️ 池内无可用动量标的，跳过本次调仓')
            return

        ranking = sorted(moms.items(), key=lambda kv: kv[1], reverse=True)
        top1_code, top1_m = ranking[0]
        hold_n = min(int(self.p.top_n), len(ranking))
        target = [c for c, _ in ranking[:hold_n]]
        ranking_text = ' | '.join(f'{c} {m * 100:+.1f}%' for c, m in ranking[:hold_n])
        self.log(f'📊 动量前{hold_n}: {ranking_text}')

        # 铁律④ 冷却过滤
        blocked = [c for c in target if self._in_cooldown(c)]
        if blocked:
            self.log('🧊 冷却中跳过: ' + ' '.join(blocked))
            target = [c for c in target if c not in blocked]
        if not target:
            self.log('⚠️ 目标全在冷却，本周不动')
            return

        # 铁律③ 换仓门槛
        holdings = [data._name for data in self._pool_datas if self.getposition(data).size > 0]
        allow = (
            self._last_top1 is None
            or (top1_code != self._last_top1 and top1_m > self.p.rotate_gain)
            or len(holdings) < len(target)
        )
        if not allow:
            self.log(f'⚪ top1未变或涨幅不足（{top1_code} {top1_m * 100:+.1f}%）→ 本周不动')
            return
        self._last_top1 = top1_code

        self._execute_rebalance_orders(target, holdings)

    def _execute_rebalance_orders(self, target: list[str], holdings: list[str]) -> None:
        """铁律⑤执行：先卖不在目标池的持仓，再对新增目标等权买入。"""
        for data in self._pool_datas:
            if self.getposition(data).size > 0 and data._name not in target:
                self.log(f'📤 卖出 {data._name}')
                self.order_target_size(data=data, target=0)
        to_buy = [code for code in target if code not in holdings]
        if not to_buy:
            return
        per_seat = float(self.broker.getvalue()) * 0.95 / len(target)
        for code in to_buy:
            data = next(d for d in self._pool_datas if d._name == code)
            size = self._lots(data, per_seat)
            if size > 0:
                self.buy(data=data, size=size)
                self.log(f'📥 买入 {code} {size}股 目标市值≈{per_seat:.0f}')

    def _check_stop_loss(self) -> None:
        """铁律④：每日检查，-8% 止损并登记冷却。"""
        for data in self._pool_datas:
            pos = self.getposition(data)
            if pos.size <= 0 or not pos.price:
                continue
            if float(data.close[0]) < float(pos.price) * self.p.stop_ratio:
                self.order_target_size(data=data, target=0)
                self._cooldown[data._name] = self._bar_no
                self.log(
                    f'🛑 止损 {data._name}（成本{pos.price:.3f} 现价{data.close[0]:.3f}，'
                    f'盈亏{(data.close[0] / pos.price - 1) * 100:+.1f}%）→ 冷却{self.p.cooldown_days}个交易日'
                )
