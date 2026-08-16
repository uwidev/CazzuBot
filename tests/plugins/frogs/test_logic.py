"""Frogs service (logic) layer — pure economy tests."""

from __future__ import annotations

import pytest

from cazzubot.errors import UserInputError
from cazzubot.models import FrogState
from plugins.frogs.effects import ExpPayload
from plugins.frogs.logic import ensure_consume_amount


def test_exp_per_frog() -> None:
    leaf = ExpPayload(exp=10, frozen_exp=3)
    assert leaf.per_frog(FrogState.NORMAL) == 10
    assert leaf.per_frog(FrogState.FROZEN) == 3

    classy = ExpPayload(exp=20, frozen_exp=6)
    assert classy.per_frog(FrogState.NORMAL) == 20
    assert classy.per_frog(FrogState.FROZEN) == 6
    assert classy.total(FrogState.FROZEN, 2) == 12


def test_ensure_consume_amount() -> None:
    ensure_consume_amount(1, 5)  # fine
    with pytest.raises(UserInputError):
        ensure_consume_amount(0, 5)
    with pytest.raises(UserInputError):
        ensure_consume_amount(6, 5)
