"""Frogs service (logic) layer — pure economy tests."""

from __future__ import annotations

import pytest

from cazzubot.errors import UserInputError
from cazzubot.models import FrogTypeEnum
from plugins.frogs.logic import (
    consume_total_exp,
    ensure_consume_amount,
    exp_per_frog,
)


def test_exp_per_frog() -> None:
    assert exp_per_frog(FrogTypeEnum.NORMAL) == 10
    assert exp_per_frog(FrogTypeEnum.FROZEN) == 3
    assert consume_total_exp(FrogTypeEnum.FROZEN, 2) == 6


def test_ensure_consume_amount() -> None:
    ensure_consume_amount(1, 5)  # fine
    with pytest.raises(UserInputError):
        ensure_consume_amount(0, 5)
    with pytest.raises(UserInputError):
        ensure_consume_amount(6, 5)
