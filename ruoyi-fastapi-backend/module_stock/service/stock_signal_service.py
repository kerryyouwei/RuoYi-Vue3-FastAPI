"""基于 Backtrader 迷你重放的当日交易信号计算服务。"""

import contextlib
import io
from datetime import datetime
from typing import Any

from exceptions.exception import ServiceException
from module_stock.service.stock_strategy_service import StockStrategyService
from utils.log_util import logger


class StockSignalService:
    """在最新一根 K 线上重放策略并读取其持有/买入/卖出信号。"""

    @classmethod
    def compute_signal(
        cls,
        strategy_name: str,
        code: str,
        strategy_params: dict[str, Any] | None,
        end_date: str,
        close_price: float | None = None,
    ) -> dict[str, Any]:
        """
        加载历史日线并（可选）追加当日快照收盘价，仅重放最后一根 K 线读取信号。

        :return: {'signal': 买入/卖出/持有, 'reason': str, 'close': float | None}
        """
        try:
            import backtrader as bt  # noqa: PLC0415

            from youw_test.strategies import load_strategy  # noqa: PLC0415
        except ImportError as exc:
            raise ServiceException(message='缺少 Backtrader 或其运行依赖') from exc

        strategy_cls = load_strategy(strategy_name)
        params = StockStrategyService._coerce_strategy_params(strategy_name, strategy_params or {})
        warmup_bars = StockStrategyService._strategy_warmup_bars(strategy_cls, params)
        data_start = StockStrategyService._warmup_start_date(str(end_date)[:10], warmup_bars)
        data = StockStrategyService._load_stock_data(code, data_start, str(end_date)[:10])
        if data is None or data.empty:
            return {'signal': '持有', 'reason': '无历史行情数据', 'close': None}

        target = datetime.strptime(str(end_date)[:10], '%Y-%m-%d').date()
        last_date = data.index[-1].date()
        if last_date < target and close_price is not None:
            appended = StockStrategyService._finite(close_price)
            if appended is not None and appended > 0:
                import pandas as pd  # noqa: PLC0415

                row = pd.DataFrame(
                    {'open': [appended], 'high': [appended], 'low': [appended], 'close': [appended], 'volume': [0]},
                    index=[pd.Timestamp(target)],
                )
                data = pd.concat([data, row])
                data = data[~data.index.duplicated(keep='last')].sort_index()

        if data.empty:
            return {'signal': '持有', 'reason': '无有效历史行情数据', 'close': None}

        final_date = data.index[-1].date()
        logs = io.StringIO()
        with contextlib.redirect_stdout(logs):
            cerebro = bt.Cerebro(stdstats=False)
            cerebro.adddata(bt.feeds.PandasData(dataname=data), name=code)
            cerebro.addstrategy(StockStrategyService._live_start_strategy(strategy_cls, final_date), **params)
            cerebro.broker.setcash(1000000)
            strategy = cerebro.run()[0]

        signal = getattr(strategy, 'signal', None) or '持有'
        reason = getattr(strategy, 'signal_reason', '') or ''
        last_close = StockStrategyService._finite(float(data['close'].iloc[-1]))
        logger.bind(strategy_name=strategy_name, code=code, end_date=str(end_date)[:10], signal=signal).debug('交易信号计算完成')
        return {'signal': signal, 'reason': reason, 'close': last_close}
