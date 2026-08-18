"""Experience -> level math (port of v1's ``src/levels_helper.py``).

Level requirements follow a cosine "wave" bounded by asymptotic envelopes.
Cumulative requirements are memoized; lookups double the memo when needed.
"""

import logging
from enum import Enum, auto
from math import cos, pi

_log = logging.getLogger(__name__)

CYCLES = 10
SKEW = 0

_UP_X_INIT = 0.6
_UP_Y_LIM = 1
_UP_Y_APPROACH = 3

_LOW_X_INIT = 0.5
_LOW_Y_LIM = 0.8
_LOW_Y_APPROACH = 2

_X_SCALE = 100
_Y_SCALE = 450

_levels_exp_memo: dict[int, float] = {0: 0}
# parallel to the memo: _levels_exp_values[i] == _levels_exp_memo[i], kept
# sorted so level_from_exp can binary-search without rebuilding the dict
_levels_exp_values: list[float] = [0.0]


class BoundingType(Enum):
    """Which asymptotic envelope bounds the level curve: upper or lower."""

    UPPER = auto()
    LOWER = auto()


def exp_to_level_cum(n: int) -> float:
    """Cumulative exp required from level 0 to level n (memoized)."""
    if n <= 0:
        return 0

    if n in _levels_exp_memo:
        return _levels_exp_memo[n]

    last_key = max(_levels_exp_memo)
    for i in range(last_key + 1, n + 1):
        value = exp_for_level(i) + _levels_exp_memo[i - 1]
        _levels_exp_memo[i] = value
        _levels_exp_values.append(value)
    return _levels_exp_memo[n]


def level_from_exp(exp: int) -> int:
    """Level for a given amount of exp."""
    if exp <= 0:
        return 0

    while True:
        res = _bin_up(_levels_exp_values, exp)
        if res != -1:
            return res

        last_level = max(_levels_exp_memo) or 1
        _log.info("Doubling memoized levels to %s", last_level * 2)
        exp_to_level_cum(last_level * 2)


def exp_for_level(n: int) -> float:
    """Exp required to go from level n-1 to level n."""
    return _Y_SCALE * _combined(n / _X_SCALE)


def _base(x: float) -> float:
    """The cosine wave offset at ``x``, in [0, 1]."""
    m = 1 - SKEW
    return 0.5 * (1 + cos(pi * (-CYCLES * x**m % 1)))


def _bound(x: float, x_0: float, y_inf: float, y_rate: float) -> float:
    """Asymptotic envelope approaching ``y_inf`` as ``x`` grows."""
    return (y_inf - x_0) * (
        1 - (1 / ((y_inf - x_0) * x + 1)) ** y_rate
    ) + x_0


def _bound_by(x: float, mode: BoundingType) -> float:
    """The envelope for ``mode`` at ``x``."""
    if mode == BoundingType.UPPER:
        return _bound(x, _UP_X_INIT, _UP_Y_LIM, _UP_Y_APPROACH)
    return _bound(x, _LOW_X_INIT, _LOW_Y_LIM, _LOW_Y_APPROACH)


def _combined(x: float) -> float:
    """Wave-modulated value bounded between the two envelopes."""
    upper = _bound_by(x, BoundingType.UPPER)
    lower = _bound_by(x, BoundingType.LOWER)
    return (upper - lower) * _base(x) + lower


def _bin_up(arr: list[float], target: int) -> int:
    """Index i where arr[i] <= target < arr[i+1]; -1 if out of range."""
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = left + (right - left) // 2
        if mid + 1 >= len(arr):
            break
        if arr[mid] <= target < arr[mid + 1]:
            return mid
        if target > arr[mid]:
            left = mid + 1
        else:
            right = mid - 1
    return -1
