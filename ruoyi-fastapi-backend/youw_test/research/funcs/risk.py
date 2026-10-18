"""函数层积木：仓位函数（risk）与 walk-forward 窗口切分。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


def equal_weight(codes: list[str], max_weight: float = 0.20) -> dict[str, float]:
    """等权仓位，单票不超过上限。"""
    if not codes:
        return {}
    weight = min(1.0 / len(codes), max_weight)
    return {code: weight for code in codes}


def position_atr(
    inv_vol: dict[str, float],
    max_weight: float = 0.20,
    total: float = 0.95,
) -> dict[str, float]:
    """ATR 逆波动率仓位：按 1/波动率 归一化，单票设上限。

    inv_vol: code -> 1/ATR（或 1/波动率）。值<=0 或缺失按 0 处理。
    """
    positive = {code: value for code, value in inv_vol.items() if value > 0}
    if not positive:
        return {}
    total_inv = sum(positive.values())
    weights = {code: total * value / total_inv for code, value in positive.items()}
    capped = {code: min(weight, max_weight) for code, weight in weights.items()}
    return capped


# ---------------------------------------------------------------- walk-forward


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: date
    train_end: date
    valid_start: date
    valid_end: date

    def as_dict(self) -> dict[str, str]:
        return {
            'trainStart': self.train_start.isoformat(),
            'trainEnd': self.train_end.isoformat(),
            'validStart': self.valid_start.isoformat(),
            'validEnd': self.valid_end.isoformat(),
        }


def walk_forward_windows(
    start: date,
    end: date,
    train_years: int = 2,
    valid_years: int = 1,
    step_years: int = 1,
) -> list[WalkForwardWindow]:
    """按自然年滚动切分 walk-forward 窗口。

    窗口示例（train=2, valid=1, step=1）：
      训练 2019-2020 → 验证 2021
      训练 2020-2021 → 验证 2022
    验证段不足一个完整年时按实际区间截断（不早于 end）。
    """
    if train_years <= 0 or valid_years <= 0 or step_years <= 0 or end < start:
        return []
    windows: list[WalkForwardWindow] = []
    valid_year = start.year + train_years
    while True:
        vs = date(valid_year, 1, 1)
        ve = date(valid_year + valid_years - 1, 12, 31)
        ve = min(ve, end)
        if vs > end:
            break
        windows.append(
            WalkForwardWindow(
                train_start=date(vs.year - train_years, 1, 1),
                train_end=date(vs.year - 1, 12, 31),
                valid_start=vs,
                valid_end=ve,
            )
        )
        if ve >= end:
            break
        valid_year += step_years
    return windows
