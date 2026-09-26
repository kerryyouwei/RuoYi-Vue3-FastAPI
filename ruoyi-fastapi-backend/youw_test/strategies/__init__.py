"""Backtrader 策略插件加载器。"""

import importlib
import re

import backtrader as bt


def load_strategy(name):
    """按模块名加载策略；策略模块必须导出 Strategy 类。"""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError(f"无效的策略名称: {name!r}")

    try:
        module = importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        if exc.name == f"{__name__}.{name}":
            raise ValueError(f"未找到策略插件: {name}") from exc
        raise

    strategy_class = getattr(module, "Strategy", None)
    if not isinstance(strategy_class, type) or not issubclass(
        strategy_class, bt.Strategy
    ):
        raise TypeError(f"策略插件 {name} 必须导出 Backtrader Strategy 类")
    return strategy_class

