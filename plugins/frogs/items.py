"""Frog items — the *item* half of the frog split.

``species.py`` is the capturable entity (its behavior: spawn, catch).
This module is the **frog item**: what a caught frog *is* as an inventory
object — immutable ``item_id`` (the oracle), display name/icon, the
description card, and its **item-owned consume** behavior.

What consuming an item does is the ITEM's decision and is written as code:
the per-item glue invokes the statuses the item declares (e.g.
``POG_REACTION``) — and nothing else. Exp is a pure measure of chatting
(2026-09 decision): no item grants exp, so no frog item writes an exp log
row and no frog-side exp total exists. Statuses are unique classes owning
their own values (``plugins/frogs/statuses.py``); the item just *names* the
ones it triggers — no outbound payload objects, no registry indirection.

Each species × state is a distinct item (normal vs frozen differ), so
consumption needs no state juggling. Every item is declared as a bare
``Item`` literal — no builder indirection — and the info card's "On
consumption" field is derived from the same status classes the consume glue
applies, so display and effect cannot drift. An item whose consume has no
effect (Basic Frog, Frog Remains) declares no field at all: the consume
surface warns instead.

Frozen items are trophies, not consumables (design 2026): the seasonal
freeze preserves species identity; a frozen frog cannot be consumed —
only thawed with risk (``thaw.py``), and its info card carries an
"On thaw" field instead of "On consumption".
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

import pendulum

from core import Item
from core.errors import UserInputError
from core.statuses import Scope, Status
from core.models import FrogItemKey, FrogState

from .assets import FrogAsset
from .events import FrogConsumedEvent
from .statuses import (
    POG_REACTION,
    FROGGERS_REACTION,
    CLASSY_ROLE,
)
from .thaw import THAW_CHANCE

if TYPE_CHECKING:
    from core.bot import CazzuBot

# item-owned consume statuses: the status class instances each item triggers.
# This is the item's composition, written as code (no payload objects).
# Pog/Froggers trigger their reaction status; Classy its role status; Basic,
# frozen frogs (trophies, never consumed) and Remains trigger nothing.
_ITEM_STATUSES: dict[str, tuple[Status, ...]] = {
    "frog:pog:normal": (POG_REACTION,),
    "frog:froggers:normal": (FROGGERS_REACTION,),
    "frog:classy:normal": (CLASSY_ROLE,),
}


def item_statuses(item_id: str) -> tuple[Status, ...]:
    """The statuses an frog item triggers on consume (the item's own)."""
    return _ITEM_STATUSES.get(item_id, ())


async def _consume_item(
    bot: "CazzuBot", uid: int, amount: int, item_id: str
) -> None:
    """The item-owned consume: statuses, then the FrogConsumedEvent.

    No exp: consuming grants only the statuses the item declares (and a
    Basic Frog declares none, so its consume has no effect at all — the
    inventory surface warns about that before the member confirms). Each
    ``apply`` targets the member scope with the item id as provenance. The
    event stays last so domain observers see a *finished* consume.
    """
    _, species_str, state_str = item_id.split(":")
    species_key = FrogItemKey(species_str)
    state = FrogState(state_str)
    now = pendulum.now("UTC")

    for status in item_statuses(item_id):
        await status.apply(
            bot,
            scope=Scope.member(uid),
            provenance=item_id,
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
    """Consume glue for ``frog:basic:normal`` (no effect: no statuses)."""
    await _consume_item(bot, uid, amount, "frog:basic:normal")


async def _consume_pog_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:pog:normal`` (its own status, per the id)."""
    await _consume_item(bot, uid, amount, "frog:pog:normal")


async def _consume_froggers_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:froggers:normal`` (its own status)."""
    await _consume_item(bot, uid, amount, "frog:froggers:normal")


async def _consume_classy_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:classy:normal`` (its own status)."""
    await _consume_item(bot, uid, amount, "frog:classy:normal")


async def _consume_frozen(bot: "CazzuBot", uid: int, amount: int) -> None:
    """One shared consume glue for every frozen frog — a trophy refusal.

    All four species frozen items (``frog:<species>:frozen``) point
    at this single function: consuming any frozen frog is refused with
    the same message (the seasonal freeze preserves species identity;
    the only way out is the thaw gamble, ``thaw.py``). The
    /inventory consume command also checks this before the confirm, so
    the glue refusal is defense in depth.
    """
    raise UserInputError(
        "Frozen frogs cannot be consumed — thaw them first."
    )


# "Frog Remains" — the consolation prize of a failed thaw (owner placeholder,
# 2026). Not a species: the id is deliberately NOT ``frog:``-prefixed so the
# capture-embed/permit ``frog:`` prefix totals never count it. A memorial
# item since exp left the frog side (2026-09): consuming it grants nothing.


async def _consume_remains(bot: "CazzuBot", uid: int, amount: int) -> None:
    """Consume glue for ``remains`` — a memorial: it grants nothing.

    Kept as an explicit no-op (not ``consume=None``) so the item stays
    consumable and the inventory surface can state the plain fact before
    the member confirms, rather than refusing the act. Remains are not a
    frog (no species key), so unlike frog consumes this never emits
    ``FrogConsumedEvent`` (which carries a species key).
    """


def _consumption_fields(
    species_key: FrogItemKey,
    state: FrogState,
) -> tuple[tuple[str, str], ...]:
    """The info card's "On consumption" fields — effects only.

    Derived from the same status classes the consume glue applies, so
    display and effect cannot drift. An item whose consume has no effect
    yields no field at all (nothing to state on the card; the consume
    surface warns instead).
    """
    statuses = item_statuses(f"frog:{species_key.value}:{state.value}")
    if not statuses:
        return ()
    return (("On consumption", " ".join(s.describe() for s in statuses)),)


def _thaw_field() -> tuple[str, str]:
    """The info card's "On thaw" — frozen frogs are trophies, not consumables.

    The odds are read from the oracle that rolls them
    (``thaw.THAW_CHANCE``) instead of being written into the prose, so
    re-tuning the knob cannot leave the card lying (R7). The failure
    payout is named, not valued: Frog Remains grants nothing (2026-09).
    """
    survive = f"{THAW_CHANCE:.0%}"
    fail = f"{1 - THAW_CHANCE:.0%}"
    return (
        "On thaw",
        f"Frozen and non-consumable. Thawing this frog has a {survive} "
        f"chance to restore it, and {fail} to leave Frog Remains.",
    )


class FrogItems(Enum):
    """Every frog inventory item — the four species × state, plus Remains.

    The member is the code reference (rename freely); ``item_id`` is the
    immutable oracle. Registered as the frogs plugin's ``item_decl``. Each
    item is one bare ``Item`` literal: the description prose plus the
    field derived from the status classes the consume applies (normal —
    none for Basic, so it carries no field) or the thaw gamble (frozen).
    Frozen items reuse the normal-species art (D8) —
    distinct frozen art is assigned later. Cluster deliberately has no
    item — catching it never grants one (the burst is the catch), so it
    can never be held or consumed. Frog Remains (id ``remains``) sits
    beside the frogs but is not one: it never freezes, never thaws, and
    is excluded from every ``frog:``-prefixed total.
    """

    BASIC = Item(
        item_id="frog:basic:normal",
        display_name="Basic Frog",
        icon="🐸",
        description="The most normalest frog of them all.",
        icon_asset=FrogAsset.FROG_BASIC,
        consume=_consume_basic_normal,
        fields=_consumption_fields(FrogItemKey.BASIC, FrogState.NORMAL),
    )
    BASIC_FROZEN = Item(
        item_id="frog:basic:frozen",
        display_name="Basic Frog (Frozen)",
        icon="🧊",
        description="A basic frog frozen solid by the seasonal freeze.",
        icon_asset=FrogAsset.FROG_BASIC_FROZEN,
        consume=_consume_frozen,
        fields=(_thaw_field(),),
    )
    POG = Item(
        item_id="frog:pog:normal",
        display_name="Pog Frog",
        icon="🐸",
        description="A frog with a pog.",
        icon_asset=FrogAsset.FROG_POG,
        consume=_consume_pog_normal,
        fields=_consumption_fields(FrogItemKey.POG, FrogState.NORMAL),
    )
    POG_FROZEN = Item(
        item_id="frog:pog:frozen",
        display_name="Pog Frog (Frozen)",
        icon="🧊",
        description="A pog frog frozen solid by the seasonal freeze.",
        icon_asset=None,
        consume=_consume_frozen,
        fields=(_thaw_field(),),
    )
    FROGGERS = Item(
        item_id="frog:froggers:normal",
        display_name="Froggers Frog",
        icon="🐸",
        description="A frog with a poggers.",
        icon_asset=FrogAsset.FROG_FROGGERS,
        consume=_consume_froggers_normal,
        fields=_consumption_fields(FrogItemKey.FROGGERS, FrogState.NORMAL),
    )
    FROGGERS_FROZEN = Item(
        item_id="frog:froggers:frozen",
        display_name="Froggers Frog (Frozen)",
        icon="🧊",
        description="A froggers frog frozen solid by the seasonal freeze.",
        icon_asset=None,
        consume=_consume_frozen,
        fields=(_thaw_field(),),
    )
    CLASSY = Item(
        item_id="frog:classy:normal",
        display_name="Classy Frog",
        icon="🐸",
        description="A frog with rather refined tastes.",
        icon_asset=FrogAsset.FROG_CLASSY,
        consume=_consume_classy_normal,
        fields=_consumption_fields(FrogItemKey.CLASSY, FrogState.NORMAL),
    )
    CLASSY_FROZEN = Item(
        item_id="frog:classy:frozen",
        display_name="Classy Frog (Frozen)",
        icon="🧊",
        description="A classy frog frozen solid by the seasonal freeze.",
        icon_asset=None,
        consume=_consume_frozen,
        fields=(_thaw_field(),),
    )
    REMAINS = Item(
        item_id="remains",
        display_name="Frog Remains",
        icon="💀",
        description=(
            "The leftovers of a frozen frog that didn't survive the thaw."
        ),
        icon_asset=None,
        consume=_consume_remains,
        fields=(),
    )
