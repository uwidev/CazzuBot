"""Contains helper functions for calculating a level given experience."""
import logging
from enum import Enum, auto
from math import cos, pi


_log = logging.getLogger(__name__)

cycles = 10
skew = 0

upper_y_limit = 1
upper_x_init = 0.25
upper_y_limit_approach = 2

lower_y_limit = 0.5
lower_x_init = 0.2
lower_y_limit_approach = 2


class BoundingType(Enum):
    UPPER = auto()
    LOWER = auto()


def _base(x):
    m = 1 - skew
    return 0.5 * (1 + cos(pi * (-cycles * x**m % 1)))


def _bound(x, x_init, y_limit, y_limit_approach):
    return (y_limit - x_init) * (
        1 - (1 / ((y_limit - x_init) * x + 1)) ** y_limit_approach
    ) + x_init


def _bound_by(x, mode: BoundingType):
    if mode == BoundingType.UPPER:
        return _bound(x, upper_x_init, upper_y_limit, upper_y_limit_approach)

    return _bound(x, lower_x_init, lower_y_limit, lower_y_limit_approach)


def derive_level(x):
    upper = _bound_by(x, BoundingType.UPPER)
    lower = _bound_by(x, BoundingType.LOWER)

    return (upper - lower) * _base(x) + lower
