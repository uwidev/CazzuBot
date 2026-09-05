"""Frog items — the exp oracle and the item-owned consume composition.

The item composes what consuming does — exp from its oracle, plus the
status classes it declares (Pog/Froggers → their reaction status, Classy
→ its role status). Status values live on the classes
(``plugins/frogs/statuses.py``); the store records only provenance.

The frog modules are resolved at call time (``tests/plugins/frogs/_current.py``):
the plugin-reload tests purge and re-import ``plugins.frogs.*`` mid-suite,
so collection-time references would go stale against the registry.
"""

from __future__ import annotations

import pendulum
import pytest
from typing import TYPE_CHECKING

from cazzubot.errors import UserInputError
from cazzubot.models import FrogItemKey, FrogState
from cazzubot.statuses import Scope, status_by_source
from plugins.frogs.seams import FrogSeam

from tests.plugins.frogs._current import events, items, statuses

if TYPE_CHECKING:
    from plugins.frogs.events import FrogConsumedEvent


def test_item_statuses_cover_the_consumables() -> None:
    """Every consumable item composes its statuses; Basic composes none.

    Frozen frogs are trophies (never consumed), so they compose no
    statuses and no frozen row exists here.
    """
    it, st = items(), statuses()
    assert it._ITEM_STATUSES == {
        "frog:pog:normal": (st.POG_REACTION,),
        "frog:froggers:normal": (st.FROGGERS_REACTION,),
        "frog:classy:normal": (st.CLASSY_ROLE,),
    }
    assert it.item_statuses("frog:basic:normal") == ()
    assert it.item_statuses("frog:pog:frozen") == ()


def test_item_composes_only_its_statuses() -> None:
    """An item names exactly the statuses it triggers."""
    it, st = items(), statuses()
    assert it.item_statuses("frog:pog:normal") == (st.POG_REACTION,)
    assert it.item_statuses("frog:classy:normal") == (st.CLASSY_ROLE,)


def test_new_species_exp_oracle_values() -> None:
    """D1/D2 defaults (owner-tunable) — normal exp only.

    The frozen rows are gone: frozen frogs are never consumed (they are
    thawed instead), so no frozen exp exists in the oracle.
    """
    it = items()
    assert it.frog_exp(FrogItemKey.POG, FrogState.NORMAL) == 30
    assert it.frog_exp(FrogItemKey.FROGGERS, FrogState.NORMAL) == 300
    assert it.frog_exp(FrogItemKey.CLASSY, FrogState.NORMAL) == 200
    assert len(it._SPECIES_EXP) == 4  # cluster has no exp (no item)


def test_consume_blurb_reads_the_oracle() -> None:
    """The info card's consume text derives from the oracle (display = grant)."""
    it = items()
    assert (
        it._consume_blurb(FrogItemKey.BASIC, FrogState.NORMAL)
        == "Grants **10** seasonal exp."
    )


def test_frozen_items_carry_the_thaw_blurb() -> None:
    """Frozen info cards describe the thaw gamble, not consumption."""
    it = items()
    thaw = (
        "Frozen and non-consumable. Thawing this frog has a 50% chance "
        "to restore it, and 50% to leave Frog Remains (3 exp)."
    )
    for member in (
        it.FrogItems.BASIC_FROZEN,
        it.FrogItems.POG_FROZEN,
        it.FrogItems.FROGGERS_FROZEN,
        it.FrogItems.CLASSY_FROZEN,
    ):
        assert member.value.fields == (("On thaw", thaw),)


def test_remains_item_declared() -> None:
    """Frog Remains: a flat-exp consolation item, not a frog."""
    it = items()
    assert it._REMAINS_EXP == 3
    remains = it.FrogItems.REMAINS.value
    assert remains.item_id == "remains"
    assert remains.display_name == "Frog Remains"
    assert remains.consume is not None
    assert remains.fields == (
        ("On consumption", "Grants **3** seasonal exp."),
    )


def test_consume_blurb_describes_composed_statuses() -> None:
    """Pog/Froggers/Classy blurbs read the status classes the consume runs."""
    it = items()
    assert it._consume_blurb(FrogItemKey.POG, FrogState.NORMAL) == (
        "Grants **30** seasonal exp. For 1 hour, a **1%** chance the bot "
        + "reacts to your messages with the froggers emoji (10s cooldown)."
    )
    assert it._consume_blurb(FrogItemKey.CLASSY, FrogState.NORMAL) == (
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
    consume = items().FrogItems.POG.value.consume
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
    consume = items().FrogItems.POG.value.consume
    assert consume is not None
    await consume(bot, 123, 1)
    contribs = await bot.statuses.list(
        Scope.member(123), FrogSeam.FROG_REACTION
    )
    assert contribs and contribs[0].payload == {"from": "frog:pog:normal"}
    # the chance is read off the class, never the row
    klass = status_by_source(contribs[0].source)
    assert isinstance(klass, statuses().ReactionStatus)
    assert klass.chance == 0.01


async def test_consume_composes_item_statuses(full_bot) -> None:
    """The composition pipeline applies the item's declared status classes."""
    bot = full_bot
    uid = 123
    await bot.inventory.add(uid, "frog:froggers:normal", 1)
    consume = items().FrogItems.FROGGERS.value.consume
    assert consume is not None
    await consume(bot, uid, 1)
    contribs = await bot.statuses.list(
        Scope.member(uid), FrogSeam.FROG_REACTION
    )
    assert contribs and contribs[0].source == "frog:blessing:froggers"
    assert isinstance(
        status_by_source(contribs[0].source), statuses().ReactionStatus
    )


async def test_consume_reports_frog_consumed_event(full_bot) -> None:
    """The consume emits FrogConsumedEvent last (finished-consume signal)."""
    from plugins.experience import db as exp_db

    event_cls = events().FrogConsumedEvent  # call-time (reload-safe)
    received: list[FrogConsumedEvent] = []

    async def on_consumed(event: FrogConsumedEvent) -> None:
        received.append(event)

    bot = full_bot
    bot.events.on(event_cls, on_consumed)
    consume = items().FrogItems.BASIC.value.consume
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


async def test_frozen_consume_is_refused(full_bot) -> None:
    """Frozen frogs are trophies — their consume glue refuses the act."""
    it = items()
    for member in (
        it.FrogItems.BASIC_FROZEN,
        it.FrogItems.POG_FROZEN,
        it.FrogItems.FROGGERS_FROZEN,
        it.FrogItems.CLASSY_FROZEN,
    ):
        consume = member.value.consume
        assert consume is not None
        with pytest.raises(UserInputError, match="cannot be consumed"):
            await consume(full_bot, 123, 1)
        # nothing was granted or taken — the refusal happens before any move
        assert await full_bot.inventory.get(123, "remains") == 0
        assert await full_bot.inventory.get(123, "frog:classy:frozen") == 0


async def test_remains_consume_grants_flat_exp(full_bot) -> None:
    """Remains consume: 3 exp/unit, no statuses, no FrogConsumedEvent."""
    from plugins.experience import db as exp_db

    it = items()
    consume = it.FrogItems.REMAINS.value.consume
    assert consume is not None
    await full_bot.inventory.add(424242, "remains", 4)

    await consume(full_bot, 424242, 2)

    now = pendulum.now("UTC")
    assert (
        await exp_db.seasonal_exp(
            full_bot.db, 424242, now.year, (now.month - 1) // 3
        )
        == 6
    )  # 3 exp/unit * 2
