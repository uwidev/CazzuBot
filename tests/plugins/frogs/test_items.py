"""Frog items — the exp oracle and the item-owned consume composition.

The item composes what consuming does — exp from its oracle, plus the
status classes it declares (Pog/Froggers → their reaction status, Classy
→ its role status). Status values live on the classes
(``plugins/frogs/statuses.py``); the store records only provenance.
"""

from __future__ import annotations

import pendulum

from cazzubot.models import FrogItemKey, FrogState
from cazzubot.statuses import Scope, status_by_source
from plugins.experience import db as exp_db
from plugins.frogs.events import FrogConsumedEvent
from plugins.frogs.items import (
    FrogItems,
    _ITEM_STATUSES,
    _SPECIES_EXP,
    _consume_blurb,
    frog_exp,
    item_statuses,
)
from plugins.frogs.seams import FrogSeam
from plugins.frogs.statuses import (
    CLASSY_ROLE,
    FROGGERS_REACTION,
    POG_REACTION,
    ReactionStatus,
)


def test_item_statuses_cover_the_consumables() -> None:
    """Every consumable item composes its statuses; Basic composes none."""
    assert _ITEM_STATUSES == {
        "frog:pog:normal": (POG_REACTION,),
        "frog:pog:frozen": (POG_REACTION,),
        "frog:froggers:normal": (FROGGERS_REACTION,),
        "frog:froggers:frozen": (FROGGERS_REACTION,),
        "frog:classy:normal": (CLASSY_ROLE,),
        "frog:classy:frozen": (CLASSY_ROLE,),
    }
    assert item_statuses("frog:basic:normal") == ()


def test_item_composes_only_its_statuses() -> None:
    """An item names exactly the statuses it triggers."""
    assert item_statuses("frog:pog:normal") == (POG_REACTION,)
    assert item_statuses("frog:classy:normal") == (CLASSY_ROLE,)


def test_new_species_exp_oracle_values() -> None:
    """D1/D2 defaults (owner-tunable)."""
    assert frog_exp(FrogItemKey.POG, FrogState.NORMAL) == 30
    assert frog_exp(FrogItemKey.FROGGERS, FrogState.NORMAL) == 300
    assert frog_exp(FrogItemKey.CLASSY, FrogState.NORMAL) == 200
    assert frog_exp(FrogItemKey.POG, FrogState.FROZEN) == 15
    assert frog_exp(FrogItemKey.FROGGERS, FrogState.FROZEN) == 150
    assert frog_exp(FrogItemKey.CLASSY, FrogState.FROZEN) == 100
    assert len(_SPECIES_EXP) == 4  # cluster has no exp (no item)


def test_consume_blurb_reads_the_oracle() -> None:
    """The info card's consume text derives from the oracle (display = grant)."""
    assert (
        _consume_blurb(FrogItemKey.BASIC, FrogState.NORMAL)
        == "Grants **10** seasonal exp."
    )
    assert (
        _consume_blurb(FrogItemKey.BASIC, FrogState.FROZEN)
        == "Grants **3** seasonal exp."
    )


def test_consume_blurb_describes_composed_statuses() -> None:
    """Pog/Froggers/Classy blurbs read the status classes the consume runs."""
    assert _consume_blurb(FrogItemKey.POG, FrogState.NORMAL) == (
        "Grants **30** seasonal exp. For 1 hour, a **1%** chance the bot "
        + "reacts to your messages with the froggers emoji (10s cooldown)."
    )
    assert _consume_blurb(FrogItemKey.CLASSY, FrogState.NORMAL) == (
        "Grants **200** seasonal exp. Grants the **Classy** role for 3 "
        + "hours."
    )


async def test_consume_grants_exp_and_publishes_status(
    full_bot,
) -> None:
    """Consuming a Pog grants exp AND applies its reaction status."""
    bot = full_bot
    uid = 123
    await bot.inventory.add(uid, "frog:pog:normal", 2)
    consume = FrogItems.POG.value.consume
    assert consume is not None
    await consume(bot, uid, 1)
    # the item glue does not decrement — /inventory consume owns the stack
    assert await bot.inventory.get(uid, "frog:pog:normal") == 2
    contribs = await bot.statuses.list(
        Scope.member(uid), FrogSeam.FROG_REACTION
    )
    assert contribs and contribs[0].source == "frog:blessing:pog"


async def test_provenance_is_item_id(full_bot) -> None:
    """The store row's only payload is provenance — the granting item id."""
    bot = full_bot
    consume = FrogItems.POG.value.consume
    assert consume is not None
    await consume(bot, 123, 1)
    contribs = await bot.statuses.list(
        Scope.member(123), FrogSeam.FROG_REACTION
    )
    assert contribs and contribs[0].payload == {"from": "frog:pog:normal"}
    # the chance is read off the class, never the row
    status = status_by_source(contribs[0].source)
    assert isinstance(status, ReactionStatus)
    assert status.chance == 0.01


async def test_consume_composes_item_statuses(full_bot) -> None:
    """The composition pipeline applies the item's declared status classes."""
    bot = full_bot
    uid = 123
    await bot.inventory.add(uid, "frog:froggers:normal", 1)
    consume = FrogItems.FROGGERS.value.consume
    assert consume is not None
    await consume(bot, uid, 1)
    contribs = await bot.statuses.list(
        Scope.member(uid), FrogSeam.FROG_REACTION
    )
    assert contribs and contribs[0].source == "frog:blessing:froggers"
    assert isinstance(status_by_source(contribs[0].source), ReactionStatus)


async def test_consume_reports_frog_consumed_event(full_bot) -> None:
    """The consume emits FrogConsumedEvent last (finished-consume signal)."""
    received: list[FrogConsumedEvent] = []

    async def on_consumed(event: FrogConsumedEvent) -> None:
        received.append(event)

    bot = full_bot
    bot.events.on(FrogConsumedEvent, on_consumed)
    consume = FrogItems.BASIC.value.consume
    assert consume is not None
    await consume(bot, 424242, 2)

    now = pendulum.now("UTC")
    assert (
        await exp_db.seasonal_exp(
            bot.db, 424242, now.year, (now.month - 1) // 3
        )
        == 20
    )  # 10 exp/unit * 2
    assert len(received) == 1
    assert received[0].uid == 424242
    assert received[0].species_key is FrogItemKey.BASIC
    assert received[0].amount == 2
    assert received[0].state is FrogState.NORMAL