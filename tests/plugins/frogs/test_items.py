"""Frog items — the item-owned consume composition (statuses only).

The item composes what consuming does: the status classes it declares
(Pog/Froggers → their reaction status, Classy → its role status) and
nothing else — no item grants exp (2026-09). Status values live on the
classes (``plugins/frogs/statuses.py``); the store records only
provenance.

The frog modules are resolved at call time (``tests/plugins/frogs/_current.py``):
the plugin-reload tests purge and re-import ``plugins.frogs.*`` mid-suite,
so collection-time references would go stale against the registry.
"""

from __future__ import annotations

import pytest
from typing import TYPE_CHECKING

from core.errors import UserInputError
from core.models import FrogItemKey, FrogState
from core.statuses import Scope, status_by_source
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


def test_no_item_grants_exp() -> None:
    """Exp is chatting-only (2026-09): no frog item carries an exp oracle.

    The consume glues write no exp rows, so the old ``frog_exp`` /
    ``REMAINS_EXP`` machinery is gone rather than left dangling.
    """
    it = items()
    for name in ("frog_exp", "exp_grant_for", "_SPECIES_EXP", "REMAINS_EXP"):
        assert not hasattr(it, name), name


def test_basic_item_card_states_no_effect() -> None:
    """A Basic consume has no effect, so its card carries no field."""
    it = items()
    assert it._consumption_fields(FrogItemKey.BASIC, FrogState.NORMAL) == ()
    assert it.FrogItems.BASIC.value.fields == ()


def test_frozen_items_carry_the_thaw_blurb() -> None:
    """Frozen info cards describe the thaw gamble, not consumption."""
    it = items()
    thaw = (
        "Frozen and non-consumable. Thawing this frog has a 50% chance "
        "to restore it, and 50% to leave Frog Remains."
    )
    for member in (
        it.FrogItems.BASIC_FROZEN,
        it.FrogItems.POG_FROZEN,
        it.FrogItems.FROGGERS_FROZEN,
        it.FrogItems.CLASSY_FROZEN,
    ):
        assert member.value.fields == (("On thaw", thaw),)


def test_thaw_blurb_reads_the_oracles(monkeypatch) -> None:
    """The card's odds derive from the knob the thaw service rolls (R7).

    Re-tuning ``thaw.THAW_CHANCE`` must move the prose with it —
    hand-written numbers would silently lie.
    """
    it = items()
    monkeypatch.setattr(it, "THAW_CHANCE", 0.25)
    assert it._thaw_field() == (
        "On thaw",
        "Frozen and non-consumable. Thawing this frog has a 25% chance "
        "to restore it, and 75% to leave Frog Remains.",
    )


def test_remains_item_declared() -> None:
    """Frog Remains: a memorial item, not a frog — consuming grants nothing."""
    it = items()
    remains = it.FrogItems.REMAINS.value
    assert remains.item_id == "remains"
    assert remains.display_name == "Frog Remains"
    assert remains.consume is not None
    assert remains.fields == ()


def test_consumption_fields_describe_composed_statuses() -> None:
    """Pog/Froggers/Classy cards read the status classes the consume runs."""
    it = items()
    assert it._consumption_fields(
        FrogItemKey.POG, FrogState.NORMAL
    ) == (
        (
            "On consumption",
            "For 1 hour, a **1%** chance the bot reacts to your messages "
            "with the froggers emoji (10s cooldown).",
        ),
    )
    assert it._consumption_fields(
        FrogItemKey.CLASSY, FrogState.NORMAL
    ) == (
        ("On consumption", "Grants the **Classy** role for 3 hours."),
    )


async def test_consume_publishes_status_and_no_exp(full_bot) -> None:
    """Consuming a Pog applies its reaction status and grants no exp."""
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
    assert (
        await bot.db.fetchval("SELECT COUNT(*) FROM member_exp_log") == 0
    )


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
    event_cls = events().FrogConsumedEvent  # call-time (reload-safe)
    received: list[FrogConsumedEvent] = []

    async def on_consumed(event: FrogConsumedEvent) -> None:
        received.append(event)

    bot = full_bot
    bot.events.on(event_cls, on_consumed)
    consume = items().FrogItems.BASIC.value.consume
    assert consume is not None
    await consume(bot, 424242, 2)

    # a Basic consume grants nothing at all — not even an exp log row
    assert (
        await bot.db.fetchval(
            "SELECT COUNT(*) FROM member_exp_log WHERE uid = 424242"
        )
        == 0
    )
    assert len(received) == 1
    assert received[0].uid == 424242
    assert received[0].species_key is FrogItemKey.BASIC
    assert received[0].amount == 2
    assert received[0].state is FrogState.NORMAL


async def test_frozen_consume_is_refused(full_bot) -> None:
    """Frozen frogs are trophies — one shared glue refuses the act."""
    it = items()
    for member in (
        it.FrogItems.BASIC_FROZEN,
        it.FrogItems.POG_FROZEN,
        it.FrogItems.FROGGERS_FROZEN,
        it.FrogItems.CLASSY_FROZEN,
    ):
        consume = member.value.consume
        assert consume is not None
        # every frozen species routes through the SAME function — there is
        # exactly one frozen-consume path, not four copies of the refusal
        assert consume is it._consume_frozen
        with pytest.raises(UserInputError, match="cannot be consumed"):
            await consume(full_bot, 123, 1)
        # nothing was granted or taken — the refusal happens before any move
        assert await full_bot.inventory.get(123, "remains") == 0
        assert await full_bot.inventory.get(123, "frog:classy:frozen") == 0


async def test_remains_consume_grants_nothing(full_bot) -> None:
    """Remains consume: a memorial — no exp rows, no statuses, no event."""
    it = items()
    consume = it.FrogItems.REMAINS.value.consume
    assert consume is not None
    await full_bot.inventory.add(424242, "remains", 4)

    await consume(full_bot, 424242, 2)

    assert (
        await full_bot.db.fetchval(
            "SELECT COUNT(*) FROM member_exp_log WHERE uid = 424242"
        )
        == 0
    )
    contribs = await full_bot.statuses.list(
        Scope.member(424242), FrogSeam.FROG_REACTION
    )
    assert contribs == []
