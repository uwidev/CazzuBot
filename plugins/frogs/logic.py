"""Frogs service layer — pure economy decisions, no discord objects.

Spawn timing lives in the core type ``InChaotic`` (interval ± jitter
rolls) and the species roll in ``species.roll_species``; this module holds
the consume-side decisions for the ``exp`` effect. The scheduler handler
and capture view remain controllers (scheduling + discord side effects);
the consume *effect* (exp grant) lives in ``effects.py``.
"""

from __future__ import annotations

from cazzubot.errors import UserInputError
from cazzubot.models import FrogState

from .effects import ExpPayload


def exp_per_frog(payload: ExpPayload, state: FrogState) -> int:
    """Exp granted per frog for ``payload`` consumed in ``state``."""
    return payload.frozen_exp if state is FrogState.FROZEN else payload.exp


def consume_total_exp(
    payload: ExpPayload, state: FrogState, amount: int
) -> int:
    """Total exp for consuming ``amount`` frogs of a payload in a state."""
    return exp_per_frog(payload, state) * amount


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
