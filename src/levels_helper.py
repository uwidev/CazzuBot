"""Contains helper functions for calculating a level given experience."""
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

_levels_exp_memo = {0: 0}


class BoundingType(Enum):
    UPPER = auto()
    LOWER = auto()


def exp_to_level_cum(n: int):
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
        _levels_exp_memo[i] = exp_to_level(i) + _levels_exp_memo[i - 1]

    return _levels_exp_memo[n]


def level_from_exp(exp: int):
    """Calculate the level given exp.

    If a lower bin for levels is not found, double the pre-computed memo since it's
    possible to we may need more queries within this double range.
    """
    if not exp or exp <= 0:
        return 0

    while True:
        res = _bin_up(list(_levels_exp_memo.values()), exp)

        if res != -1:
            return res

        last_level = 1 if not _get_last_memo()[0] else _get_last_memo()[0]
        _log.info(
            "Doubling memoized levels to %s",
            last_level * 2,
        )
        exp_to_level_cum(last_level * 2)


def exp_to_level(n: int):
    """Calcuate the exp required to level up from n-1 to n."""
    return _Y_SCALE * _combined(n / _X_SCALE)


def _base(x):
    m = 1 - SKEW
    return 0.5 * (1 + cos(pi * (-CYCLES * x**m % 1)))


def _bound(x, x_0, y_inf, y_rate):
    return (y_inf - x_0) * (1 - (1 / ((y_inf - x_0) * x + 1)) ** y_rate) + x_0


def _bound_by(x, mode: BoundingType):
    if mode == BoundingType.UPPER:
        return _bound(x, _UP_X_INIT, _UP_Y_LIM, _UP_Y_APPROACH)

    return _bound(x, _LOW_X_INIT, _LOW_Y_LIM, _LOW_Y_APPROACH)


def _combined(x):
    upper = _bound_by(x, BoundingType.UPPER)
    lower = _bound_by(x, BoundingType.LOWER)

    return (upper - lower) * _base(x) + lower


def _get_last_memo():
    """Return a [level,exp] of the last last memo."""
    return list(_levels_exp_memo.items())[-1]


def _bin_up(arr, target):
    """Return the index i in which the target fits in i and i+1 through binary search.

    arr is supposed to be an 'infinite' memoized series. We want to find the index in
    which target is greater than arr[i], but less than arr[i+1]. If we are at arr[n], we
    cannot check for arr[n+1] because that's out of index. We want to return -1, and the
    caller should expand arr and call this function again to try to find the index.
    """
    left, right = 0, len(arr) - 1

    while left <= right:
        mid = left + (right - left) // 2

        # If checking forward is out of scope, break and return -1
        # to generate more levels to look up.
        if mid + 1 >= len(arr):
            break

        if arr[mid] <= target and target < arr[mid + 1]:
            return mid

        if target > arr[mid]:
            left = mid + 1
        else:
            right = mid - 1

    return -1  #
