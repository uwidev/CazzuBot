"""Frog items — the *item* half of the frog split.

``species.py`` is the **capturable entity** (its behavior: spawn, catch
outcome). This module is the **frog item**: what a caught frog *is* as an
inventory object — its immutable ``item_id`` (the oracle stored in
``inventory.item``, byte-identical to the legacy strings so there is no
migration), its display name/icon, its description card, and its
**item-owned consume** behavior.

What consuming an item does is the ITEM's decision (owner 2026-08-28):
it grants seasonal exp from its ``frog_exp`` oracle and composes the
outcomes it produces (``_SPECIES_OUTCOMES`` — Basic composes none;
Pog/Froggers the reaction outcome, Classy the role outcome). Outcomes
are generic, scope-aware primitives (``outcomes.py``) that may invoke
statuses through ``bot.statuses``; the species carries no consume
declaration.

Each species × state is a distinct item (normal vs frozen give different
exp), so consumption needs no state juggling — the item's ``consume`` grants
its own per-unit value. Every item is declared as a bare ``Item`` literal —
no builder indirection — and both the consume grant and the info card's
"On consumption" field read the ``frog_exp`` oracle, so display and grant
cannot drift.
"""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING

import pendulum

from cazzubot import Item
from cazzubot.statuses import Scope
from cazzubot.models import (
    FrogState,
    MemberExpLogSourceEnum,
    FrogItemKey,
)

from plugins.experience import db as exp_db

from .assets import FrogAsset
from .outcomes import OutcomePayload, ReactionPayload, RolePayload
from .events import FrogConsumedEvent

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

# species × state -> exp per unit (D1/D2 defaults; owner-tunable). The
# single source for both the consume grant and the catalog's display.
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


# item-owned consume composition (owner 2026-08-28): what consuming an
# item does is the ITEM's decision. Values live in `_SPECIES_EXP`
# (oracle); the composed outcome applications live here, beside them.
# Pog/Froggers run the shared reaction outcome (which publishes the
# reaction status — one identity, strongest chance wins); Classy runs
# the role outcome (external role seam). Cluster is deliberately absent
# — it has no item (FROG.md: "User should not be able to acquire this
# item").
_SPECIES_OUTCOMES: dict[FrogItemKey, tuple[OutcomePayload, ...]] = {
    FrogItemKey.BASIC: (),
    FrogItemKey.POG: (
        ReactionPayload(chance=0.01, duration=timedelta(hours=1)),
    ),
    FrogItemKey.FROGGERS: (
        ReactionPayload(chance=0.07, duration=timedelta(hours=1)),
    ),
    FrogItemKey.CLASSY: (
        RolePayload(
            role_dev=1542294599358353430,
            role_prod=1542293782588952696,
            duration=timedelta(hours=3),
        ),
    ),
}


def classy_role_ids() -> frozenset[int]:
    """Every role id the classy consume composition could grant.

    The single source the RoleConverger may remove (see
    plugins/frogs/__init__.py) — derived from this table so it can
    never drift from the items that actually grant roles.
    """
    ids: set[int] = set()
    for payloads in _SPECIES_OUTCOMES.values():
        for payload in payloads:
            if isinstance(payload, RolePayload):
                ids.add(payload.role_dev)
                ids.add(payload.role_prod)
    return frozenset(ids)


async def _consume_item(
    bot: "CazzuBot", uid: int, amount: int, item_id: str
) -> None:
    """The item-owned consume: exp, then the item's composed modifiers.

    The exp grant amount is derived from the item's own id via
    ``frog_exp`` — the single exp oracle — so a consume can never hand
    out a different value than the info card shows. The composed outcome
    applications (``_SPECIES_OUTCOMES``) then run as generic scope-aware
    outcomes (member scope, the item id as provenance) — the ITEM
    decides what consumption does; outcomes only modify state (some
    publish statuses). The item reports itself as a
    :class:`FrogConsumedEvent` last, keeping the domain-observer path
    alive without the generic ``/inventory consume`` knowing frogs.
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

    for payload in _SPECIES_OUTCOMES[species_key]:
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
    """The info card's "On consumption" text for a species' state.

    Reads the same sources the consume uses — the ``frog_exp`` oracle
    plus the item's own ``_SPECIES_OUTCOMES`` composition — so display
    and grant cannot drift. Each composed outcome appends its own line
    (the reaction chance, the role grant).
    """
    parts = [f"Grants **{frog_exp(species_key, state)}** seasonal exp."]
    for payload in _SPECIES_OUTCOMES.get(species_key, ()):
        if isinstance(payload, ReactionPayload):
            parts.append(
                f"For the next hour, a **{payload.chance:.0%}** chance the "
                "bot reacts to your messages with the froggers emoji "
                "(10s cooldown)."
            )
        elif isinstance(payload, RolePayload):
            parts.append("Grants the **Classy** role for **3 hours**.")
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
    consumption field read from the ``frog_exp`` oracle. Frozen items
    reuse the normal-species art (D8); Cluster deliberately has no item —
    it can never be caught, so it can never be held or consumed.
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
