"""Frog items — the *item* half of the frog split.

``species.py`` is the capturable entity (its behavior: spawn, catch).
This module is the **frog item**: what a caught frog *is* as an inventory
object — immutable ``item_id`` (the oracle), display name/icon, the
description card, and its **item-owned consume** behavior.

What consuming an item does is the ITEM's decision and is written as code:
the per-item glue grants seasonal exp from the ``frog_exp`` oracle and
invokes the statuses the item declares (e.g. ``POG_REACTION``). Statuses
are unique classes owning their own values (``plugins/frogs/statuses.py``);
the item just *names* the ones it triggers — no outbound payload objects,
no registry indirection.

Each species × state is a distinct item (normal vs frozen give different
exp), so consumption needs no state juggling — the item's ``consume`` grants
its own per-unit value. Every item is declared as a bare ``Item`` literal —
no builder indirection — and both the consume grant and the info card's
"On consumption" field read the ``frog_exp`` oracle + the status classes,
so display and grant cannot drift.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

import pendulum

from cazzubot import Item
from cazzubot.statuses import Scope, Status
from cazzubot.models import (
    FrogState,
    MemberExpLogSourceEnum,
    FrogItemKey,
)

from plugins.experience import db as exp_db

from .assets import FrogAsset
from .events import FrogConsumedEvent
from .statuses import (
    POG_REACTION,
    FROGGERS_REACTION,
    CLASSY_ROLE,
)

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

# species × state -> exp per unit (D1/D2 defaults; owner-tunable). The
# single source for both the consume grant and the catalog's display.
# Cluster is deliberately absent: catching it never grants an item, so no
# exp exists for it.
_SPECIES_EXP: dict[FrogItemKey, dict[FrogState, int]] = {
    FrogItemKey.BASIC: {
        FrogState.NORMAL: 10,
        FrogState.FROZEN: 3,
    },
    FrogItemKey.POG: {
        FrogState.NORMAL: 30,
        FrogState.FROZEN: 15,
    },
    FrogItemKey.FROGGERS: {
        FrogState.NORMAL: 300,
        FrogState.FROZEN: 150,
    },
    FrogItemKey.CLASSY: {
        FrogState.NORMAL: 200,  # owner-set placeholder (D1)
        FrogState.FROZEN: 100,
    },
}


def frog_exp(species_key: FrogItemKey, state: FrogState) -> int:
    """Seasonal exp granted by one unit of a species' item in ``state``."""
    return _SPECIES_EXP[species_key][state]


def has_item(species_key: FrogItemKey) -> bool:
    """Whether a capture of the species ever grants an inventory item.

    The single oracle for "does the item exist": Cluster deliberately has
    no item (its catch bursts instead), so the catalog skips the consume
    line here and the inventory never holds it.
    """
    return species_key in _SPECIES_EXP


# item-owned consume statuses: the status class instances each item triggers.
# This is the item's composition, written as code (no payload objects).
# Pog/Froggers trigger their reaction status; Classy its role status; Basic
# (and Cluster — no item at all) trigger nothing.
_ITEM_STATUSES: dict[str, tuple[Status, ...]] = {
    "frog:pog:normal": (POG_REACTION,),
    "frog:pog:frozen": (POG_REACTION,),
    "frog:froggers:normal": (FROGGERS_REACTION,),
    "frog:froggers:frozen": (FROGGERS_REACTION,),
    "frog:classy:normal": (CLASSY_ROLE,),
    "frog:classy:frozen": (CLASSY_ROLE,),
}


def item_statuses(item_id: str) -> tuple[Status, ...]:
    """The statuses an frog item triggers on consume (the item's own)."""
    return _ITEM_STATUSES.get(item_id, ())


async def _consume_item(
    bot: "CazzuBot", uid: int, amount: int, item_id: str
) -> None:
    """The item-owned consume: exp, statuses, then the FrogConsumedEvent.

    The exp grant derives from the item's own id via ``frog_exp`` (the
    single oracle). The item's statuses are the classes it declares above;
    each ``apply`` to the member scope with the item id as provenance.
    The event stays last so domain observers see a *finished* consume.
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
    """Consume glue for ``frog:basic:normal`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:basic:normal")


async def _consume_basic_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:basic:frozen`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:basic:frozen")


async def _consume_pog_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:pog:normal`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:pog:normal")


async def _consume_pog_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:pog:frozen`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:pog:frozen")


async def _consume_froggers_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:froggers:normal`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:froggers:normal")


async def _consume_froggers_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:froggers:frozen`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:froggers:frozen")


async def _consume_classy_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:classy:normal`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:classy:normal")


async def _consume_classy_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:classy:frozen`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:classy:frozen")


def _consume_blurb(species_key: FrogItemKey, state: FrogState) -> str:
    """The info card's "On consumption" — reads the same sources the glue
    uses (``frog_exp`` + the item's declared status classes), so display
    and grant cannot drift."""
    parts = [f"Grants **{frog_exp(species_key, state)}** seasonal exp."]
    for status in item_statuses(f"frog:{species_key.value}:{state.value}"):
        parts.append(status.describe())
    return " ".join(parts)


def _consumption_field(
    species_key: FrogItemKey,
    state: FrogState,
) -> tuple[str, str]:
    """The info card's "On consumption" (label, text) for a species' state."""
    return ("On consumption", _consume_blurb(species_key, state))


class FrogItems(Enum):
    """Every frog inventory item — basic/pog/froggers/classy × normal/frozen.

    The member is the code reference (rename freely); ``item_id`` is the
    immutable oracle. Registered as the frogs plugin's ``item_decl``. Each
    item is one bare ``Item`` literal: the description prose plus the
    consumption field derived from the oracle and the status classes.
    Frozen items reuse the normal-species art (D8); Cluster deliberately
    has no item — catching it never grants one (the burst is the catch),
    so it can never be held or consumed.
    """

    BASIC = Item(
        item_id="frog:basic:normal",
        display_name="Basic Frog",
        icon="🐸",
        description="The most normalest frog of them all.",
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
    POG = Item(
        item_id="frog:pog:normal",
        display_name="Pog Frog",
        icon="🐸",
        description="A frog with a pog.",
        icon_asset=FrogAsset.FROG_POG,
        consume=_consume_pog_normal,
        fields=(_consumption_field(FrogItemKey.POG, FrogState.NORMAL),),
    )
    POG_FROZEN = Item(
        item_id="frog:pog:frozen",
        display_name="Pog Frog (Frozen)",
        icon="🐸",
        description="A pog frog frozen solid by the seasonal freeze.",
        icon_asset=FrogAsset.FROG_POG,
        consume=_consume_pog_frozen,
        fields=(_consumption_field(FrogItemKey.POG, FrogState.FROZEN),),
    )
    FROGGERS = Item(
        item_id="frog:froggers:normal",
        display_name="Froggers Frog",
        icon="🐸",
        description="A frog with a poggers.",
        icon_asset=FrogAsset.FROG_FROGGERS,
        consume=_consume_froggers_normal,
        fields=(
            _consumption_field(FrogItemKey.FROGGERS, FrogState.NORMAL),
        ),
    )
    FROGGERS_FROZEN = Item(
        item_id="frog:froggers:frozen",
        display_name="Froggers Frog (Frozen)",
        icon="🐸",
        description="A froggers frog frozen solid by the seasonal freeze.",
        icon_asset=FrogAsset.FROG_FROGGERS,
        consume=_consume_froggers_frozen,
        fields=(
            _consumption_field(FrogItemKey.FROGGERS, FrogState.FROZEN),
        ),
    )
    CLASSY = Item(
        item_id="frog:classy:normal",
        display_name="Classy Frog",
        icon="🐸",
        description="A frog with rather refined tastes.",
        icon_asset=FrogAsset.FROG_CLASSY,
        consume=_consume_classy_normal,
        fields=(_consumption_field(FrogItemKey.CLASSY, FrogState.NORMAL),),
    )
    CLASSY_FROZEN = Item(
        item_id="frog:classy:frozen",
        display_name="Classy Frog (Frozen)",
        icon="🐸",
        description="A classy frog frozen solid by the seasonal freeze.",
        icon_asset=FrogAsset.FROG_CLASSY,
        consume=_consume_classy_frozen,
        fields=(_consumption_field(FrogItemKey.CLASSY, FrogState.FROZEN),),
    )
