"""函数层积木测试：entry/filter/exit 纯函数 + 未来数据探针 + walk-forward 切分 + BH 校正。"""

from datetime import date

import pandas as pd
import pytest

from youw_test.research.funcs.entry import ENTRIES, breakout_20d, mom_breakout
from youw_test.research.funcs.exit import fixed_days_exit
from youw_test.research.funcs.filter import liquidity_filter, st_filter, turnover_filter
from youw_test.research.funcs.risk import equal_weight, position_atr, walk_forward_windows
from youw_test.research.funcs.stats import benjamini_hochberg, binom_two_sided_pvalue
from youw_test.research.golden_tests import make_frame
from youw_test.research.golden_tests import run_all as run_golden_tests


# ---------------------------------------------------------------- entry 函数


def test_breakout_20d_insufficient_bars() -> None:
    frame = make_frame([10.0, 10.5, 11.0])
    assert breakout_20d(frame) is False


def test_breakout_20d_triggers_on_new_high() -> None:
    closes = [10.0] * 25 + [10.5]
    frame = make_frame(closes)
    assert breakout_20d(frame, lookback=20) is True


def test_breakout_20d_no_signal_below_prior_max() -> None:
    closes = [10.0] * 21 + [9.5]
    frame = make_frame(closes)
    assert breakout_20d(frame, lookback=20) is False


def test_mom_breakout_threshold() -> None:
    rising = list(__import__('numpy').linspace(10, 12, 30))  # +20%
    frame = make_frame(rising)
    assert mom_breakout(frame, period=20, threshold=0.05) is True
    assert mom_breakout(frame, period=20, threshold=0.30) is False


def test_all_entries_have_golden_metadata() -> None:
    for name, entry in ENTRIES.items():
        assert entry.meta.min_bars > 0
        assert entry.meta.version
        assert entry.meta.golden_cases


# ---------------------------------------------------------------- 过滤器


def test_turnover_filter() -> None:
    assert turnover_filter({'turn': 1.0}) is True
    assert turnover_filter({'turn': 0.1}) is False
    assert turnover_filter({'turn': 50.0}) is False
    assert turnover_filter({}) is True  # 缺失降级


def test_st_filter() -> None:
    assert st_filter({'isst': 0}) is True
    assert st_filter({'isst': 1}) is False
    assert st_filter({}) is True


def test_liquidity_filter() -> None:
    assert liquidity_filter({'amount': 10_000_000}) is True
    assert liquidity_filter({'amount': 1_000}) is False
    assert liquidity_filter({}) is True


# ---------------------------------------------------------------- 出场函数


def test_fixed_days_exit() -> None:
    assert fixed_days_exit(entry_bar=0, current_bar=9, days=10) is False
    assert fixed_days_exit(entry_bar=0, current_bar=10, days=10) is True


# ---------------------------------------------------------------- 仓位函数


def test_equal_weight_caps_single_weight() -> None:
    weights = equal_weight(['A', 'B'], max_weight=0.2)
    assert weights == {'A': 0.2, 'B': 0.2}

    weights = equal_weight(['A', 'B', 'C', 'D', 'E', 'F'], max_weight=0.2)
    assert all(w <= 0.2 for w in weights.values())


def test_position_atr_inverse_volatility() -> None:
    weights = position_atr({'A': 1.0, 'B': 3.0}, max_weight=0.9)
    assert weights['B'] > weights['A']
    assert pytest.approx(sum(weights.values()), abs=1e-9) == 0.95


def test_position_atr_handles_invalid() -> None:
    assert position_atr({}) == {}
    assert position_atr({'A': 0, 'B': -1}) == {}


# ---------------------------------------------------------------- walk-forward 切分


def test_walk_forward_windows_standard() -> None:
    windows = walk_forward_windows(date(2019, 1, 1), date(2025, 12, 31))
    assert len(windows) == 5
    first = windows[0]
    assert (first.train_start, first.train_end) == (date(2019, 1, 1), date(2020, 12, 31))
    assert (first.valid_start, first.valid_end) == (date(2021, 1, 1), date(2021, 12, 31))
    last = windows[-1]
    assert last.valid_end == date(2025, 12, 31)


def test_walk_forward_windows_truncated_tail() -> None:
    windows = walk_forward_windows(date(2019, 1, 1), date(2023, 6, 30))
    last = windows[-1]
    assert last.valid_end == date(2023, 6, 30)


def test_walk_forward_windows_invalid_range() -> None:
    assert walk_forward_windows(date(2020, 1, 1), date(2019, 1, 1)) == []
    assert walk_forward_windows(date(2020, 1, 1), date(2020, 6, 30), train_years=2) == []


# ---------------------------------------------------------------- 统计工具


def test_binom_pvalue_symmetric() -> None:
    # 10次全胜 vs 0胜 的 p 值相同（双侧对称）
    assert pytest.approx(binom_two_sided_pvalue(10, 10), abs=1e-9) == binom_two_sided_pvalue(0, 10)
    assert binom_two_sided_pvalue(10, 10) < 0.01
    assert binom_two_sided_pvalue(5, 10) > 0.5


def test_benjamini_hochberg_basic() -> None:
    adjusted = benjamini_hochberg([0.01, 0.04, 0.03, 0.005])
    assert adjusted[3] == pytest.approx(0.02)
    assert adjusted[0] == pytest.approx(0.02)
    assert all(a >= p for a, p in zip(adjusted, [0.01, 0.04, 0.03, 0.005]))


# ---------------------------------------------------------------- 黄金测试集整体运行


def test_golden_tests_all_pass() -> None:
    results = run_golden_tests()
    failures = [r for r in results if not r[1]]
    assert not failures, f'黄金测试失败: {failures}'
