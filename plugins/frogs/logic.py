"""Frogs service layer — pure economy decisions, no discord objects.

Spawn timing lives in the core type ``InChaotic`` (interval ± jitter
rolls); this module holds the consume-side decisions. The scheduler
handler and capture view remain controllers (scheduling + discord side
effects).
"""

from __future__ import annotations

from cazzubot.errors import UserInputError
from cazzubot.models import FrogTypeEnum

_EXP_PER_FROG: dict[FrogTypeEnum, int] = {
    FrogTypeEnum.NORMAL: 10,
    FrogTypeEnum.FROZEN: 3,
}


def exp_per_frog(frog_type: FrogTypeEnum) -> int:
    """Exp granted per frog consumed."""
    return _EXP_PER_FROG[frog_type]


def consume_total_exp(frog_type: FrogTypeEnum, amount: int) -> int:
    """Total exp for consuming ``amount`` frogs of a type."""
    return exp_per_frog(frog_type) * amount


def ensure_consume_amount(amount: int, balance: int) -> None:
    """Raise ``UserInputError`` when a consume request is impossible."""
    if amount < 1:
        raise UserInputError(
            "Amount of frogs to consume must be greater than 0."
        )
    if balance < amount:
        raise UserInputError(
            f"Member does not have enough frogs ({balance}) to consume."
        )
