"""Frog items — the *item* half of the frog split.

``species.py`` is the **capturable entity** (its behavior: spawn, catch
effect). This module is the **frog item**: what a caught frog *is* as an
inventory object — its immutable ``item_id`` (the oracle stored in
``inventory.item``, byte-identical to the legacy strings so there is no
migration), its display name/icon, and its **item-owned consume** behavior
(grant seasonal exp).

Each species × state is a distinct item (normal vs frozen give different
exp), so consumption needs no state juggling — the item's ``consume`` grants
its own per-unit value.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

import pendulum

from cazzubot import Item
from cazzubot.models import (
    FrogState,
    MemberExpLogSourceEnum,
    FrogItemKey,
)

from plugins.experience import db as exp_db

from .assets import FrogAsset
from .events import FrogConsumedEvent

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

# Per-item seasonal exp when one unit is consumed (item-owned — NOT on the
# entity). Keeps the legacy values: basic 10/3.
_LEAF_NORMAL = 10
_LEAF_FROZEN = 3

# species × state -> exp per unit, the single source for both the item
# defs below and the catalog's consume display.
_SPECIES_EXP: dict[FrogItemKey, dict[FrogState, int]] = {
    FrogItemKey.BASIC: {
        FrogState.NORMAL: _LEAF_NORMAL,
        FrogState.FROZEN: _LEAF_FROZEN,
    },
}


def frog_exp(species_key: FrogItemKey, state: FrogState) -> int:
    """Seasonal exp granted by one unit of a species' item in ``state``."""
    return _SPECIES_EXP[species_key][state]


async def _consume_item(
    bot: "CazzuBot",
    uid: int,
    amount: int,
    *,
    item_id: str,
    exp_per: int,
) -> None:
    """Grant seasonal exp for ``amount`` units, then report the frog consume.

    The consume is item-owned, but frogs-domain observers (the future badge
    system) subscribe via ``bot.events`` — so after the exp grant the item
    reports itself as a :class:`FrogConsumedEvent`, keeping that path alive
    without the generic ``/inventory consume`` knowing about frogs.
    """
    now = pendulum.now("UTC")
    await exp_db.add_exp_log(
        bot.db,
        uid,
        exp_per * amount,
        now,
        source=MemberExpLogSourceEnum.FROG,
    )
    _, species_str, state_str = item_id.split(":")
    await bot.events.emit(
        FrogConsumedEvent(
            uid=uid,
            species_key=FrogItemKey(species_str),
            amount=amount,
            state=FrogState(state_str),
            at=now.isoformat(),
        )
    )


def _frog_item(
    item_id: str,
    display_name: str,
    icon: str,
    exp_per: int,
    icon_asset: Enum | None = None,
) -> Item:
    """Build a frog item whose consume grants ``exp_per`` seasonal exp/unit."""

    async def _consume(bot: "CazzuBot", uid: int, amount: int) -> None:
        await _consume_item(
            bot, uid, amount, item_id=item_id, exp_per=exp_per
        )

    return Item(
        item_id=item_id,
        display_name=display_name,
        icon=icon,
        icon_asset=icon_asset,
        consume=_consume,
    )


class FrogItems(Enum):
    """Every frog inventory item — basic × normal/frozen.

    The member is the code reference (rename freely); ``item_id`` is the
    immutable oracle. Registered as the frogs plugin's ``item_decl``.
    """

    BASIC = _frog_item(
        "frog:basic:normal",
        "Basic Frog",
        "🐸",
        frog_exp(FrogItemKey.BASIC, FrogState.NORMAL),
        icon_asset=FrogAsset.FROG_BASIC,
    )
    BASIC_FROZEN = _frog_item(
        "frog:basic:frozen",
        "Basic Frog (Frozen)",
        "🐸",
        frog_exp(FrogItemKey.BASIC, FrogState.FROZEN),
        icon_asset=FrogAsset.FROG_BASIC_FROZEN,
    )
