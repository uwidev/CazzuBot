"""Frog items — the *item* half of the frog split.

``species.py`` is the **capturable entity** (its behavior: spawn, catch
effect). This module is the **frog item**: what a caught frog *is* as an
inventory object — its immutable ``item_id`` (the oracle stored in
``inventory.item``, byte-identical to the legacy strings so there is no
migration), its display name/icon, its description card, and its
**item-owned consume** behavior.

What consuming an item does is the ITEM's decision (owner 2026-08-28):
it grants seasonal exp from its ``frog_exp`` oracle and composes the
state-modifying effects it applies (``_SPECIES_CONSUME`` — empty for the
only existing species, Basic). Effects are generic, scope-aware
modifiers (``effects.py``); the species carries no consume declaration.

Each species × state is a distinct item (normal vs frozen give different
exp), so consumption needs no state juggling — the item's ``consume`` grants
its own per-unit value. Every item is declared as a bare ``Item`` literal —
no builder indirection — and both the consume grant and the info card's
"On consumption" field read the ``frog_exp`` oracle, so display and grant
cannot drift.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

import pendulum

from cazzubot import Item
from cazzubot.effects import Scope
from cazzubot.models import (
    FrogState,
    MemberExpLogSourceEnum,
    FrogItemKey,
)

from plugins.experience import db as exp_db

from .assets import FrogAsset
from .effects import EffectPayload
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


# item-owned consume composition (owner 2026-08-28): what consuming an
# item does is the ITEM's decision. Values live in `_SPECIES_EXP`
# (oracle); the composed effect applications live here, beside them.
# No species composes an effect yet — Basic's tuple is empty and the
# pipeline is proven by the dispatcher test; Phase 2 of the frog-species
# plan fills in the reaction/role payloads.
_SPECIES_CONSUME: dict[FrogItemKey, tuple[EffectPayload, ...]] = {
    FrogItemKey.BASIC: (),
}


async def _consume_item(
    bot: "CazzuBot", uid: int, amount: int, item_id: str
) -> None:
    """The item-owned consume: exp, then the item's composed modifiers.

    The exp grant amount is derived from the item's own id via
    ``frog_exp`` — the single exp oracle — so a consume can never hand
    out a different value than the info card shows. The composed effect
    applications (``_SPECIES_CONSUME``) then run as generic scope-aware
    modifiers (member scope, the item id as provenance) — the ITEM
    decides what consumption does; the modifiers only modify state. The
    item reports itself as a :class:`FrogConsumedEvent` last, keeping
    the domain-observer path alive without the generic
    ``/inventory consume`` knowing frogs.
    """
    _, species_str, state_str = item_id.split(":")
    species_key = FrogItemKey(species_str)
    state = FrogState(state_str)
    exp = frog_exp(species_key, state) * amount

    now = pendulum.now("UTC")
    await exp_db.add_exp_log(
        bot.db,
        uid,
        exp,
        now,
        source=MemberExpLogSourceEnum.FROG,
    )

    for payload in _SPECIES_CONSUME[species_key]:
        await payload.key.value.consume(
            bot,
            payload,
            scope=Scope.member(uid),
            provenance=item_id,
            amount=amount,
            now=now,
        )

    await bot.events.emit(
        FrogConsumedEvent(
            uid=uid,
            species_key=species_key,
            amount=amount,
            state=state,
            at=now.isoformat(),
        )
    )


async def _consume_basic_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:basic:normal`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:basic:normal")


async def _consume_basic_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:basic:frozen`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:basic:frozen")


def _consume_blurb(species_key: FrogItemKey, state: FrogState) -> str:
    """The info card's "On consumption" text for a species' state.

    Reads the same sources the consume uses — the ``frog_exp`` oracle
    plus the item's own ``_SPECIES_CONSUME`` composition — so display
    and grant cannot drift. No species composes an effect yet (Basic's
    composition is empty), so the text is the exp line; Phase-2 composed
    modifiers append their lines here.
    """
    return f"Grants **{frog_exp(species_key, state)}** seasonal exp."


def _consumption_field(
    species_key: FrogItemKey,
    state: FrogState,
) -> tuple[str, str]:
    """The info card's "On consumption" (label, text) for a species' state."""
    return ("On consumption", _consume_blurb(species_key, state))


class FrogItems(Enum):
    """Every frog inventory item — basic × normal/frozen.

    The member is the code reference (rename freely); ``item_id`` is the
    immutable oracle. Registered as the frogs plugin's ``item_decl``. Each
    item is one bare ``Item`` literal: the description prose plus the
    consumption field read from the ``frog_exp`` oracle.
    """

    BASIC = Item(
        item_id="frog:basic:normal",
        display_name="Basic Frog",
        icon="🐸",
        description="A plain frog found hopping around Club Cirno's grounds.",
        icon_asset=FrogAsset.FROG_BASIC,
        consume=_consume_basic_normal,
        fields=(_consumption_field(FrogItemKey.BASIC, FrogState.NORMAL),),
    )
    BASIC_FROZEN = Item(
        item_id="frog:basic:frozen",
        display_name="Basic Frog (Frozen)",
        icon="🐸",
        description="A basic frog frozen solid by the seasonal freeze.",
        icon_asset=FrogAsset.FROG_BASIC_FROZEN,
        consume=_consume_basic_frozen,
        fields=(_consumption_field(FrogItemKey.BASIC, FrogState.FROZEN),),
    )
