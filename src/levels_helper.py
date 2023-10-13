"""Contains helper functions for calculating a level given experience."""
import logging
from enum import Enum, auto
from math import cos, pi


_log = logging.getLogger(__name__)

CYCLES = 10
SKEW = 0

UP_X_INIT = 0.6
UP_Y_LIM = 1
UP_Y_APPROACH = 3

LOW_X_INIT = 0.4
LOW_Y_LIM = 0.8
LOW_Y_APPROACH = 2

X_SCALE = 100
Y_SCALE = 500

_levels_exp_memo = {0: 0}
_levels_exp_memo_r = {0: 0}  # Reversed dict


class BoundingType(Enum):
    UPPER = auto()
    LOWER = auto()


def cum_exp_to(n: int):
    """Calculate the cumulative exp requirement from level 0 to level n.

    This is iteratively memoized to prevent wasteful recomputing of lower levels.
    """
    if n <= 0:
        return 0

    global _levels_exp_memo  # noqa: PLW0602

    if n in _levels_exp_memo:
        return _levels_exp_memo[n]

    last_key = list(_levels_exp_memo)[-1] if list(_levels_exp_memo)[-1] else 1

    for i in range(last_key, n + 1):
        _levels_exp_memo[i] = exp_to(i) + _levels_exp_memo[i - 1]
        _levels_exp_memo_r[_levels_exp_memo[i]] = i  # Add into reversed dict

    return _levels_exp_memo[n]


def level_from_exp(exp: int):
    """Calculate the level given exp.

    If a lower bin for levels is not found, double the pre-computed memo since it's
    possible to we may need more queries within this double range.
    """
    if exp <= 0:
        return 0

    while True:
        res = _binary_lower_bin(list(_levels_exp_memo_r), exp)

        if res != -1:
            return res

        last_level = 1 if not _get_last_memo()[0] else _get_last_memo()[0]
        _log.info(
            "Doubling memoized levels to %s",
            last_level * 2,
        )
        cum_exp_to(last_level * 2)


def exp_to(n: int):
    """Calcuate the exp required to level up from n-1 to n."""
    return Y_SCALE * _combined(n / X_SCALE)


def _base(x):
    m = 1 - SKEW
    return 0.5 * (1 + cos(pi * (-CYCLES * x**m % 1)))


def _bound(x, x_0, y_inf, y_rate):
    return (y_inf - x_0) * (1 - (1 / ((y_inf - x_0) * x + 1)) ** y_rate) + x_0


def _bound_by(x, mode: BoundingType):
    if mode == BoundingType.UPPER:
        return _bound(x, UP_X_INIT, UP_Y_LIM, UP_Y_APPROACH)

    return _bound(x, LOW_X_INIT, LOW_Y_LIM, LOW_Y_APPROACH)


def _combined(x):
    upper = _bound_by(x, BoundingType.UPPER)
    lower = _bound_by(x, BoundingType.LOWER)

    return (upper - lower) * _base(x) + lower


def _get_last_memo():
    """Return a (level,exp) of the last last memo."""
    return list(_levels_exp_memo)[-1], list(_levels_exp_memo_r)[-1]


def _binary_lower_bin(arr, target):
    """Return the index i in which the target fits in i and i+1.

    If the target does not fit in between, and is instead on the edge index n or 0,
    return -1.
    """
    left, right = 0, len(arr) - 1

    while left < right:
        mid = left + (right - left) // 2

        if arr[mid] <= target and target < arr[mid + 1]:
            return mid

        if target > arr[mid]:
            left = mid + 1
        else:
            right = mid - 1

    return -1
