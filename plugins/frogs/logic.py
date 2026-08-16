"""Frogs service layer — pure economy decisions, no discord objects.

Spawn timing lives in the core type ``InChaotic`` (interval ± jitter
rolls) and the species roll in ``species.roll_species``; this module holds
the consume-side validation for the ``exp`` effect. The scheduler handler
and capture view remain controllers (scheduling + discord side effects);
the consume *effect* (exp grant) lives in ``effects.py``, where
``ExpPayload.per_frog``/``total`` own the per-state exp math.
"""

from __future__ import annotations

from cazzubot.errors import UserInputError


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
