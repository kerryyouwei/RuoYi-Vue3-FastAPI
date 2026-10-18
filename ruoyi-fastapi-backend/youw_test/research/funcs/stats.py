"""统计工具：二项检验 p 值与 Benjamini-Hochberg 校正。"""

from __future__ import annotations

import math


def binom_two_sided_pvalue(wins: int, n: int, p: float = 0.5) -> float:
    """二项分布双侧 p 值（精确计算，n 不大时直接枚举）。"""
    if n <= 0:
        return 1.0
    log_comb_cache = [math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) for k in range(n + 1)]

    def pmf(k: int) -> float:
        if k < 0 or k > n:
            return 0.0
        return math.exp(log_comb_cache[k] + k * math.log(p) + (n - k) * math.log(1 - p))

    observed = pmf(wins)
    tail = sum(pmf(k) for k in range(n + 1) if pmf(k) <= observed + 1e-15)
    return min(1.0, tail)


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    """BH 校正，返回调整后的 p 值列表（保持输入顺序）。"""
    n = len(pvalues)
    if n == 0:
        return []
    indexed = sorted(enumerate(pvalues), key=lambda item: item[1])
    adjusted = [0.0] * n
    running = 1.0
    for rank in range(n, 0, -1):
        idx, value = indexed[rank - 1]
        running = min(running, value * n / rank)
        adjusted[idx] = min(1.0, running)
    return adjusted
