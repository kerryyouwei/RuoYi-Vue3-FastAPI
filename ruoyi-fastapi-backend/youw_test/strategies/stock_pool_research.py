"""股票池研究回测（完整版）—— 多因子打分 + 执行层约束。

对应《股票池回测思路.md》第三层"执行层重放"策略：
  ① 沪深300 收盘<MA20 且 MA20<MA60 → 弱市清仓
  ② 多因子打分选股：score = w1·rank(动量) + w2·rank(低换手) + w3·rank(量能趋势)
  ③ 可交易性过滤：非停牌/非ST/上市>N天/流动性门槛（增强数据缺失时降级推导）
  ④ 执行约束：信号 t 收盘 → t+1 开盘限价单成交；开盘封板不成交；T+1；
     单笔买入金额 ≤ 信号日成交额 × amount_cap_pct
  ⑤ -8% 止损 + 20 个交易日冷却 + top1 换人门槛防磨损

标的池由回测引擎按 pool_codes 快照动态加载（datas[0]=沪深300主时钟，
datas[1:] 为股票池）；主时钟为指数 feed（无增强字段），股票 feed 可带
增强字段（StockPoolFeed），字段缺失时逐项降级。
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import backtrader as bt

from youw_test.research.funcs.market_rules import (
    MIN_LISTED_DAYS,
    T1Ledger,
    buy_limit_price,
    is_tradable_row,
    is_st_row,
    sell_limit_price,
)
from .base import BaseStrategy

DISPLAY_NAME = '股票池研究回测（完整版）'
CATEGORY = 'research'
DESCRIPTION = (
    '多因子打分(动量/低换手/量能)topN轮动；沪深300弱市清仓；'
    'tradable过滤+次日开盘限价单+封板不成交+T+1+成交量约束；'
    '-8%止损+20交易日冷却+top1换人门槛'
)
IS_PORTFOLIO = True
_REGIME_MA_SHORT = 20
_REBALANCE_MAX_GAP_DAYS = 7


class Strategy(BaseStrategy):
    params = (
        # --- 信号参数（walk-forward 可搜索） ---
        ('mom_period', 20),
        ('vol_ma_period', 10),
        ('regime_ma_period', 60),
        ('top_n', 5),
        ('w_mom', 0.6),
        ('w_turn', 0.2),
        ('w_vol', 0.2),
        # --- 防磨损 / 风控 ---
        ('rotate_gain', 0.05),
        ('stop_ratio', 0.92),
        ('cooldown_days', 20),
        # --- 执行层参数（固定，不搜索） ---
        ('max_weight', 0.20),
        ('amount_cap_pct', 0.01),
        ('min_amount', 5_000_000),
        ('min_turn', 0.3),
        ('max_wait_bars', 1),
        ('seat_ratio', 0.95),
    )

    def __init__(self) -> None:
        super().__init__()
        self._pool_datas = [d for d in self.datas[1:] if d._name != self.datas[0]._name]
        self._last_top1: str | None = None
        self._cooldown: dict[str, int] = {}
        self._bar_no = 0
        self._last_rebalance: date | None = None
        self._first_bar: dict[str, date] = {}
        self._master_first_bar: date | None = None
        self._t1 = T1Ledger()
        # order.ref -> {'data': name, 'side': 'buy'/'sell', 'placed_bar': int, 'reason': str, 'signal_date': str}
        self._pending: dict[int, dict] = {}
        self._order_meta: dict[int, dict] = {}
        self.limit_blocked_orders = 0

    # ---------- 增强字段访问 ----------

    def _line(self, data: bt.DataBase, name: str) -> float | None:
        """读取增强 line 当前值；feed 无该 line 或值为 NaN 返回 None。"""
        line = getattr(data, name, None)
        if line is None:
            return None
        try:
            value = line[0]
        except IndexError:
            return None
        if value is None or value != value:  # NaN
            return None
        return float(value)

    def _row(self, data: bt.DataBase) -> dict[str, float]:
        return {
            'volume': self._line(data, 'volume'),
            'amount': self._line(data, 'amount'),
            'tradestatus': self._line(data, 'tradestatus'),
            'isst': self._line(data, 'isst'),
            'turn': self._line(data, 'turn'),
        }

    def _listed_days(self, data: bt.DataBase, master_date: date) -> float:
        """上市天数近似。

        数据窗口起点即有行情的标的视为上市已久（首 bar 日期受 warmup 截断，
        无法还原真实 IPO 日期）；窗口中段才开始有行情的，按 (master_date - 首 bar)
        计为新上市/复牌标的。
        """
        code = data._name
        first = self._first_bar.get(code)
        if first is None:
            return MIN_LISTED_DAYS
        master_first = self._master_first_bar
        if master_first is not None and first <= master_first + timedelta(days=10):
            return MIN_LISTED_DAYS
        return (master_date - first).days

    def _is_tradable(self, data: bt.DataBase, master_date: date) -> bool:
        row = self._row(data)
        # 数据行缺失 volume 时不阻止（普通 PandasData 一定有 volume；防御异常 feed）
        return is_tradable_row(
            row,
            listed_days=self._listed_days(data, master_date),
            min_amount=self.p.min_amount,
            min_turn=self.p.min_turn,
        )

    # ---------- 基础工具 ----------

    def _mom(self, data: bt.DataBase, period: int) -> float | None:
        closes = data.close.get(size=period + 1)
        if closes is None or len(closes) < period + 1 or closes[0] <= 0:
            return None
        return closes[-1] / closes[0] - 1

    def _vol_trend(self, data: bt.DataBase, period: int) -> float | None:
        volumes = data.volume.get(size=period)
        if volumes is None or len(volumes) < period:
            return None
        ma = sum(volumes) / len(volumes)
        if ma <= 0:
            return None
        return volumes[-1] / ma - 1

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

    def _pending_codes(self, side: str) -> set[str]:
        return {rec['data'] for rec in self._pending.values() if rec['side'] == side}

    def _cancel_pending(self, code: str, side: str | None = None) -> None:
        """撤销某标的的挂单；成交/取消的最终处理统一在 notify_order。"""
        for ref, rec in list(self._pending.items()):
            if rec['data'] != code or (side is not None and rec['side'] != side):
                continue
            order = rec['order']
            if order.alive():
                self.cancel(order)

    def _cancel_stale_orders(self) -> None:
        for ref, rec in list(self._pending.items()):
            if self._bar_no - rec['placed_bar'] > self.p.max_wait_bars:
                order = rec['order']
                if order.alive():
                    self.cancel(order)
                    self.log(
                        f'⏳ 取消未成交{rec["side"]}限价单 {rec["data"]}'
                        f'（挂单{rec["placed_bar"]}，原因：{rec["reason"]}）'
                    )

    def _limit_prices_for(self, data: bt.DataBase) -> tuple[float, float]:
        """t+1 日的 (买入限价, 卖出限价)。preclose(t+1)=close(t)（同复权基准）。"""
        preclose = float(data.close[0])
        code = data._name
        is_st = is_st_row(self._row(data))
        return buy_limit_price(preclose, code, is_st), sell_limit_price(preclose, code, is_st)

    # ---------- 主流程 ----------

    def next(self) -> None:
        master_date = self.datas[0].datetime.date(0)
        self._bar_no += 1
        if self._master_first_bar is None:
            try:
                self._master_first_bar = self.datas[0].datetime.date(0)
            except Exception:  # noqa: BLE001
                pass
        for data in self._pool_datas:
            if data._name not in self._first_bar:
                try:
                    self._first_bar[data._name] = data.datetime.date(0)
                except Exception:  # noqa: BLE001 - feed 未就绪时跳过
                    pass
        self._cancel_stale_orders()
        due = (
            self._last_rebalance is None
            or master_date.weekday() == 0
            or (master_date - self._last_rebalance).days >= _REBALANCE_MAX_GAP_DAYS
        )
        if due:
            self._last_rebalance = master_date
            self._rebalance(master_date)
        self._check_stop_loss()

    # ---------- 调仓 ----------

    def _rebalance(self, master_date: date) -> None:
        self.log(f'==== 周调仓 {master_date} | 目标持仓{self.p.top_n}只 ====')

        # 铁律① 大市择时
        if self._is_weak():
            self._last_top1 = None
            for data in self._pool_datas:
                code = data._name
                if self.getposition(data).size > 0:
                    if not self._t1.can_sell(code, self._bar_no):
                        continue
                    self._place_sell(data, reason='弱市清仓')
                self._cancel_pending(code, side='buy')
            self.log('🔴 弱市（沪深300 收盘<MA20 且 MA20<MA60）→ 清仓股票池持仓')
            return

        # 铁律③ 可交易过滤 + 动量统计（只统计当日有 bar 的股票）
        candidates: list[bt.DataBase] = []
        for data in self._pool_datas:
            if data.datetime.date(0) != master_date:
                continue
            if self._in_cooldown(data._name):
                continue
            if not self._is_tradable(data, master_date):
                continue
            if data._name in self._pending_codes('sell'):
                continue
            candidates.append(data)
        if not candidates:
            self.log('⚠️ 池内无可交易标的，跳过本次调仓')
            return

        # 铁律② 多因子打分
        moms = {d._name: self._mom(d, self.p.mom_period) for d in candidates}
        turns = {d._name: self._line(d, 'turn') for d in candidates}
        vols = {d._name: self._vol_trend(d, self.p.vol_ma_period) for d in candidates}
        rank_mom = self._benefit_ranks(moms, higher_better=True)
        rank_turn = self._benefit_ranks(turns, higher_better=False)
        rank_vol = self._benefit_ranks(vols, higher_better=True)
        scores = {
            code: self.p.w_mom * rank_mom.get(code, 0.5)
            + self.p.w_turn * rank_turn.get(code, 0.5)
            + self.p.w_vol * rank_vol.get(code, 0.5)
            for code in moms
        }
        ranking = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top1_code, top1_score = ranking[0]
        hold_n = min(int(self.p.top_n), len(ranking))
        target = [c for c, _ in ranking[:hold_n]]
        ranking_text = ' | '.join(f'{c} {s:.2f}' for c, s in ranking[:hold_n])
        self.log(f'📊 多因子前{hold_n}: {ranking_text}')

        # 铁律④ 冷却过滤
        blocked = [c for c in target if self._in_cooldown(c)]
        if blocked:
            self.log('🧊 冷却中跳过: ' + ' '.join(blocked))
            target = [c for c in target if c not in blocked]
        if not target:
            self.log('⚠️ 目标全在冷却，本周不动')
            return

        # 铁律⑤ 换仓门槛
        holdings = [d._name for d in self._pool_datas if self.getposition(d).size > 0]
        allow = (
            self._last_top1 is None
            or (top1_code != self._last_top1 and scores.get(top1_code, 0) > self.p.rotate_gain)
            or len(holdings) < len(target)
        )
        if not allow:
            self.log(f'⚪ top1未变或得分不足（{top1_code} {top1_score:.2f}）→ 本周不动')
            return
        self._last_top1 = top1_code

        self._execute_rebalance_orders(master_date, target, holdings)

    @staticmethod
    def _benefit_ranks(values: dict[str, float | None], higher_better: bool) -> dict[str, float]:
        """缺失值取中性 0.5；有效值映射到 [0,1]（1=最优）。"""
        valid = {code: v for code, v in values.items() if v is not None}
        # reverse=True：最优在前；最优映射 1.0、最差映射 0.0
        order = sorted(valid, key=valid.get, reverse=True)
        n = len(order)
        if n <= 1:
            return {code: (1.0 if n else 0.5) for code in order}
        ranks = {code: 1.0 - i / (n - 1) for i, code in enumerate(order)}
        if not higher_better:
            ranks = {code: 1.0 - r for code, r in ranks.items()}
        return ranks

    def _execute_rebalance_orders(self, master_date: date, target: list[str], holdings: list[str]) -> None:
        """先卖不在目标池的持仓，再对新增目标等权买入（限价单）。"""
        signal_date = master_date.isoformat()
        for data in self._pool_datas:
            code = data._name
            if self.getposition(data).size > 0 and code not in target:
                if not self._t1.can_sell(code, self._bar_no):
                    self.log(f'⏱️ T+1 限制，暂不能卖出 {code}')
                    continue
                self._place_sell(data, reason='调仓卖出', signal_date=signal_date)
        to_buy = [
            code
            for code in target
            if code not in holdings and code not in self._pending_codes('sell') and code not in self._pending_codes('buy')
        ]
        if not to_buy:
            return
        per_seat = float(self.broker.getvalue()) * self.p.seat_ratio / len(target)
        for code in to_buy:
            data = next(d for d in self._pool_datas if d._name == code)
            size, buy_price = self._buy_size(data, per_seat)
            if size > 0:
                self._place_buy(data, size, buy_price=buy_price, reason='多因子买入',
                                signal_date=signal_date, per_seat=per_seat)

    def _buy_size(self, data: bt.DataBase, per_seat: float) -> tuple[int, float]:
        """按手(100股)取整，受目标市值、成交量约束与可用现金共同限制。

        Backtrader 对限价单按限价（而非预期开盘价）做保证金校验，
        因此 sizing 必须用买入限价，否则会被 Margin 拒单。
        返回 (股数, 买入限价)。
        """
        buy_price, _ = self._limit_prices_for(data)
        if buy_price <= 0:
            return 0, buy_price
        cash = float(self.broker.getcash())
        value = min(per_seat, cash)
        amount = self._line(data, 'amount')
        if amount is not None:
            cap = amount * self.p.amount_cap_pct
            if cap < value:
                self.log(f'⚖️ 成交量约束 {data._name}: 单笔≤{cap:.0f}（信号日成交额{amount:.0f}×{self.p.amount_cap_pct}）')
                value = cap
        if value < buy_price * 100:
            return 0, buy_price
        size = int(value / buy_price // 100 * 100)
        info = self.broker.getcommissioninfo(data)
        while size > 0:
            cost = size * buy_price + info.getcommission(size, buy_price)
            if cost <= cash:
                break
            size -= 100
        return size, buy_price

    def _place_buy(
        self,
        data: bt.DataBase,
        size: int,
        buy_price: float,
        reason: str,
        signal_date: str,
        per_seat: float,
    ) -> None:
        order = self.buy(data=data, size=size, exectype=bt.Order.Limit, price=buy_price)
        ref = order.ref
        self._pending[ref] = {
            'order': order,
            'data': data._name,
            'side': 'buy',
            'placed_bar': self._bar_no,
            'reason': reason,
        }
        self._order_meta[ref] = {'signal_date': signal_date, 'reason': reason, 'side': 'buy', 'turn': self._line(data, 'turn')}
        self.log(f'📥 挂买单 {data._name} {size}股 限价{buy_price} 目标市值≈{per_seat:.0f}')

    def _place_sell(self, data: bt.DataBase, reason: str, signal_date: str | None = None) -> None:
        if data._name in self._pending_codes('sell'):
            return  # 已有卖单挂着，避免重复下单
        if self.getposition(data).size <= 0:
            return
        if signal_date is None:
            signal_date = self.datas[0].datetime.date(0).isoformat()
        _, sell_price = self._limit_prices_for(data)
        order = self.close(data=data, exectype=bt.Order.Limit, price=sell_price)
        ref = order.ref
        self._pending[ref] = {
            'order': order,
            'data': data._name,
            'side': 'sell',
            'placed_bar': self._bar_no,
            'reason': reason,
        }
        self._order_meta[ref] = {'signal_date': signal_date, 'reason': reason, 'side': 'sell'}
        self.log(f'📤 挂卖单 {data._name} 限价{sell_price}（{reason}）')

    # ---------- 风控 ----------

    def _check_stop_loss(self) -> None:
        """铁律⑥：每日检查，-8% 止损并登记冷却。"""
        for data in self._pool_datas:
            code = data._name
            pos = self.getposition(data)
            if pos.size <= 0 or not pos.price:
                continue
            if float(data.close[0]) < float(pos.price) * self.p.stop_ratio:
                # 先撤未成交买单，防止同日既买又卖
                self._cancel_pending(code, side='buy')
                if not self._t1.can_sell(code, self._bar_no):
                    self.log(f'⏱️ T+1 限制，{code} 今日买入成交，止损顺延')
                    continue
                self._place_sell(data, reason=f'止损（成本{pos.price:.3f} 现价{data.close[0]:.3f}）')
                self._cooldown[code] = self._bar_no
                self.log(f'🛑 止损 {code} → 冷却{self.p.cooldown_days}个交易日')

    # ---------- 订单回调 ----------

    def notify_order(self, order) -> None:  # noqa: ANN001
        super().notify_order(order)
        ref = order.ref
        if order.status in [order.Submitted, order.Accepted]:
            return
        rec = self._pending.pop(ref, None)
        meta = self._order_meta.pop(ref, None)
        if order.status in [order.Canceled, order.Expired, order.Margin, order.Rejected]:
            if rec is not None:
                self.limit_blocked_orders += 1
            return
        if order.status == order.Completed and meta is not None:
            code = order.data._name
            if order.isbuy():
                self._t1.record_buy_fill(code, self._bar_no)
            record = self.execution_records[-1] if self.execution_records else None
            if record is not None and record.get('code') == code:
                record['signalDate'] = meta.get('signal_date')
                record['execDate'] = self.datas[0].datetime.date(0).isoformat()
                record['entryReason'] = meta.get('reason') if order.isbuy() else None
                record['exitReason'] = None if order.isbuy() else meta.get('reason')
                record['turn'] = meta.get('turn')





