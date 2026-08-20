"""Item definitions registry — the items-vs-entities separation core."""

from __future__ import annotations

from collections.abc import Iterator
from enum import Enum
from typing import TYPE_CHECKING

import pytest

from cazzubot.items import (
    NOOP,
    consumable,
    item_for,
    register_items,
    set_consumable,
    unregister_items,
    Item,
)

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot


async def _goop(_bot: "CazzuBot", _uid: int, _amount: int) -> None:
    raise AssertionError("consume handler should not run in a unit test")


class _FoodEnum(Enum):
    APPLE = Item(item_id="food:apple", display_name="Apple", icon="🍎")
    PIE = Item(
        item_id="food:pie", display_name="Pie", icon="🥧", consume=_goop
    )


class _OtherEnum(Enum):
    DUST = Item(item_id="misc:dust", display_name="Dust", icon="🪨")


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    unregister_items("food")
    unregister_items("misc")
    yield
    unregister_items("food")
    unregister_items("misc")


def test_item_id_is_the_oracle_separate_from_names() -> None:
    """renaming the enum member / display_name does not touch item_id."""
    item = _FoodEnum.APPLE.value
    assert item.item_id == "food:apple"
    assert item.display_name == "Apple"


def test_register_resolves_by_id_and_unregister_degrades() -> None:
    register_items("food", _FoodEnum)
    assert item_for("food:apple") == Item(
        item_id="food:apple", display_name="Apple", icon="🍎"
    )
    assert item_for("food:pie").consume is not None

    unregister_items("food")
    assert item_for("food:apple") is NOOP


def test_unknown_id_returns_noop_not_exception() -> None:
    register_items("food", _FoodEnum)
    assert item_for("nope:missing") is NOOP
    # noop is inert — no icon/name/consume
    assert NOOP.icon == ""
    assert NOOP.consume is None


def test_consumable_flag_gates_per_provider() -> None:
    register_items("food", _FoodEnum)
    # a registered-but-flag-unset provider is not consumable...
    assert consumable("food:pie") is False
    set_consumable("food", True)
    assert consumable("food:pie") is True
    # other providers unaffected; unknown ids are never consumable
    register_items("misc", _OtherEnum)
    assert consumable("misc:dust") is False
    assert consumable("nope:missing") is False
