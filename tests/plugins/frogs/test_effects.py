"""Frog effects — enum-as-registry, dispatch contract, and the generic
scope-aware consume modifiers (reaction + role).
"""

from __future__ import annotations

from typing import Any, cast

import pendulum
import pytest

from cazzubot.bot import CazzuBot
from cazzubot.effects import Scope
from cazzubot.models import FrogState, FrogItemKey
from plugins.experience import db as exp_db
from plugins.frogs import db as frog_db
from plugins.frogs import factory
from plugins.frogs.assets import FrogAsset
from plugins.frogs.effects import (
    EffectKey,
    ExpPayload,
    ReactionPayload,
    RoleConverger,
    RolePayload,
)
from plugins.frogs.events import FrogConsumedEvent
from plugins.frogs.items import FrogItems
from plugins.frogs.seams import FrogEffect, FrogSeam
from plugins.frogs.species import SPECIES, Species
from tests.fakes import (
    FakeInteraction,
    FakeMember,
    FakeMenuContext,
    FakeRole,
    menu_button,
    rest_of,
)

_UID = 424242


class _WrongPayload:
    """A payload with a valid key but the wrong class for the exp effect."""

    key = EffectKey.EXP


def test_every_effect_key_maps_to_a_handler() -> None:
    """The enum IS the registry: a member's value is its handler."""
    for key in EffectKey:
        handler = key.value
        assert callable(getattr(handler, "catch", None)), key
        assert callable(getattr(handler, "consume", None)), key


async def test_exp_effect_grants_payload_normal_value(
    bot: CazzuBot,
) -> None:
    """The fossil exp effect grants the payload's per-unit value.

    Consume hooks are scope-aware now (2026-08-28 separation): exp
    grants are member-scoped, and the fossil grants the payload's normal
    per-unit value — frozen exp is item-owned behavior (the oracle in
    ``items.py``), not a modifier concern.
    """
    effect = EffectKey.EXP.value
    now = pendulum.now("UTC")
    payload = ExpPayload(exp=20, frozen_exp=6)

    await effect.consume(
        bot,
        payload,
        scope=Scope.member(_UID),
        provenance="frog:basic:normal",
        amount=2,
        now=now,
    )
    assert (
        await exp_db.seasonal_exp(
            bot.db, _UID, now.year, (now.month - 1) // 3
        )
        == 40
    )  # 20 exp/frog * 2


async def test_exp_effect_catch_is_a_noop(bot: CazzuBot) -> None:
    await EffectKey.EXP.value.catch(
        bot,
        ExpPayload(exp=10, frozen_exp=3),
        uid=_UID,
        species_key=FrogItemKey.BASIC,
        now=pendulum.now("UTC"),
    )
    # nothing to assert beyond not raising — no log rows, no inventory


async def test_exp_effect_rejects_wrong_payload(bot: CazzuBot) -> None:
    """A payload of the wrong class for the key fails loudly (TypeError)."""
    with pytest.raises(TypeError, match="ExpPayload"):
        await EffectKey.EXP.value.consume(
            bot,
            cast(Any, _WrongPayload()),
            scope=Scope.member(_UID),
            provenance="frog:basic:normal",
            amount=1,
            now=pendulum.now("UTC"),
        )


async def test_species_effects_resolve(bot: CazzuBot) -> None:
    """Every species' catch-effect payload key maps to a handler."""
    for species in SPECIES:
        payload = species.catch_effect
        if payload is not None:
            assert payload.key in EffectKey, (
                f"{species.key} has unknown effect key {payload.key!r}"
            )


async def test_capture_dispatches_species_payload(
    seeded_bot: CazzuBot,
    author: FakeMember,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The capture flow hands the effect the bot + the species' payload.

    No shipped species has a catch effect, so this drives a synthetic one
    — the point: an effect only needs a payload-bearing species to fire.
    """
    calls: list[tuple[object, ...]] = []

    async def fake_catch(
        bot: object,
        payload: object,
        *,
        uid: int,
        species_key: FrogItemKey,
        now: object,
    ) -> None:
        calls.append(("catch", bot, payload, uid, species_key))

    # swap the handler the enum member maps to (its value instance)
    monkeypatch.setattr(EffectKey.EXP.value, "catch", fake_catch)

    spawned = Species(
        key=FrogItemKey.BASIC,
        name="Sparkle Frog",
        rarity="common",
        description="Crackles with static.",
        spawn_weight=1.0,
        catch_effect=ExpPayload(exp=5, frozen_exp=1),
        spawn_effect=None,
        art=FrogAsset.FROG_BASIC,
    )
    from plugins.frogs.species import by_key as real_by_key

    monkeypatch.setattr(
        factory,
        "by_key",
        lambda key: (
            spawned if key is FrogItemKey.BASIC else real_by_key(key)
        ),
    )
    await frog_db.set_message(seeded_bot.settings, {"content": "ok"})

    menu = factory.FrogCatchMenu(seeded_bot, 99, FrogItemKey.BASIC)
    mctx = FakeMenuContext(
        FakeInteraction(id=1, member=author, channel_id=99)
    )
    await menu_button(menu).callback(mctx)

    assert len(calls) == 1
    kind, bot, payload, uid, species_key = calls[0]
    assert kind == "catch"
    assert bot is seeded_bot
    assert isinstance(payload, ExpPayload)
    # the species' own catch payload instance flowed through
    assert payload.exp == 5 and payload.frozen_exp == 1
    assert uid == _UID and species_key is FrogItemKey.BASIC


async def test_frog_item_consume_grants_exp_and_reports(
    bot: CazzuBot,
) -> None:
    """The item-owned consume grants seasonal exp and reports the event.

    Consumption moved off the entity onto the item; the frog item's consume
    handler both grants the exp and emits :class:`FrogConsumedEvent` (the
    badge system's observation path), so the generic ``/inventory consume``
    need not know about frogs.
    """
    received: list[FrogConsumedEvent] = []

    async def on_consumed(event: FrogConsumedEvent) -> None:
        received.append(event)

    bot.events.on(FrogConsumedEvent, on_consumed)
    consume = FrogItems.BASIC.value.consume
    assert consume is not None
    await consume(bot, _UID, 2)

    now = pendulum.now("UTC")
    assert (
        await exp_db.seasonal_exp(
            bot.db, _UID, now.year, (now.month - 1) // 3
        )
        == 20
    )  # 10 exp/unit * 2
    assert len(received) == 1
    assert received[0].uid == _UID
    assert received[0].species_key is FrogItemKey.BASIC
    assert received[0].amount == 2
    assert received[0].state is FrogState.NORMAL


# -- reaction effect (identity-by-effect merge) ---------------------------

_REACTION_DEV_ROLE = 1542294599358353430
_REACTION_PROD_ROLE = 1542293782588952696


async def test_reaction_is_one_effect_across_items(
    full_bot: CazzuBot,
) -> None:
    """Pog and Froggers are the same effect: one row, strongest wins.

    Both publish under the shared effect identity (FrogEffect.REACTION)
    with the granting item as payload provenance; a stronger consume
    overwrites the value while keeping the window additive, a weaker one
    never downgrades — it only extends.
    """
    bot = full_bot
    now = pendulum.now("UTC")
    pog = ReactionPayload(chance=0.01, duration=pendulum.duration(hours=1))
    froggers = ReactionPayload(
        chance=0.07, duration=pendulum.duration(hours=1)
    )

    await EffectKey.REACTION.value.consume(
        bot,
        pog,
        scope=Scope.member(123),
        provenance="frog:pog:normal",
        amount=1,
        now=now,
    )
    # a stronger frog 5 min later: overwrites the value, keeps the window
    await EffectKey.REACTION.value.consume(
        bot,
        froggers,
        scope=Scope.member(123),
        provenance="frog:froggers:normal",
        amount=1,
        now=now.add(minutes=5),
    )
    contribs = await bot.effects.list(
        Scope.member(123), FrogSeam.FROG_REACTION, now=now.add(minutes=5)
    )
    assert len(contribs) == 1  # one effect, NOT one row per item
    assert contribs[0].source == FrogEffect.REACTION.key
    assert contribs[0].payload["chance"] == 0.07  # strongest wins
    assert contribs[0].payload["from"] == "frog:froggers:normal"
    # remaining 55m + new 1h, REPLACEd at T+5m -> T+2h (additive window)
    assert contribs[0].expires_at == now.add(hours=2)

    # a weaker consume never downgrades — it just extends the window
    await EffectKey.REACTION.value.consume(
        bot,
        pog,
        scope=Scope.member(123),
        provenance="frog:pog:normal",
        amount=1,
        now=now.add(minutes=30),
    )
    contribs = await bot.effects.list(
        Scope.member(123), FrogSeam.FROG_REACTION, now=now.add(minutes=30)
    )
    assert len(contribs) == 1
    assert contribs[0].payload["chance"] == 0.07  # still strongest
    assert contribs[0].expires_at == now.add(hours=3)  # 2h + 1h


async def test_reaction_expires_into_a_fresh_start(
    full_bot: CazzuBot,
) -> None:
    """After expiry a fresh consume starts anew (no stale window)."""
    bot = full_bot
    now = pendulum.now("UTC")
    payload = ReactionPayload(
        chance=0.01, duration=pendulum.duration(hours=1)
    )

    await EffectKey.REACTION.value.consume(
        bot,
        payload,
        scope=Scope.member(123),
        provenance="frog:pog:normal",
        amount=1,
        now=now,
    )
    # past the expiry: the row reads as absent and is pruned
    assert (
        await bot.effects.list(
            Scope.member(123),
            FrogSeam.FROG_REACTION,
            now=now.add(hours=2),
        )
        == []
    )
    await EffectKey.REACTION.value.consume(
        bot,
        payload,
        scope=Scope.member(123),
        provenance="frog:pog:normal",
        amount=1,
        now=now.add(hours=2),
    )
    contribs = await bot.effects.list(
        Scope.member(123), FrogSeam.FROG_REACTION, now=now.add(hours=2)
    )
    assert len(contribs) == 1
    assert contribs[0].expires_at == now.add(hours=3)  # fresh 1h from T+2h


# -- role effect (external seam + converger) -------------------------------


def test_role_payload_resolves_guild_role() -> None:
    """role_id_for picks the FROG.md role id for the guild kind."""
    payload = RolePayload(
        role_dev=_REACTION_DEV_ROLE,
        role_prod=_REACTION_PROD_ROLE,
        duration=pendulum.duration(hours=3),
    )
    assert payload.role_id_for("development") == _REACTION_DEV_ROLE
    assert payload.role_id_for("production") == _REACTION_PROD_ROLE


async def test_role_consume_resolves_guild_role_and_publishes(
    full_bot: CazzuBot,
) -> None:
    """Classy consume publishes the role seam and the world converges.

    The converger is registered in-test (Phase-1 ships the machinery
    tested but unwired — plugin-load registration is Phase 2); the
    external publish runs it synchronously, so the member now holds the
    resolved dev-guild role.
    """
    bot = full_bot
    # full_bot boots with the development guild kind (Config default)
    known = frozenset({_REACTION_DEV_ROLE, _REACTION_PROD_ROLE})
    converger = RoleConverger(known)
    rest = rest_of(bot)
    bot.effects.register_converger(FrogSeam.CLASSY_ROLE, converger)
    target = FakeMember(id=123, name="tester")
    rest.members[(bot.config.guild_id, 123)] = target

    payload = RolePayload(
        role_dev=_REACTION_DEV_ROLE,
        role_prod=_REACTION_PROD_ROLE,
        duration=pendulum.duration(hours=3),
    )
    await EffectKey.ROLE.value.consume(
        bot,
        payload,
        scope=Scope.member(123),
        provenance="frog:classy:normal",
        amount=1,
        now=pendulum.now("UTC"),
    )
    contribs = await bot.effects.list(
        Scope.member(123), FrogSeam.CLASSY_ROLE
    )
    assert (
        contribs and contribs[0].payload["role_id"] == _REACTION_DEV_ROLE
    )
    assert contribs[0].payload["from"] == "frog:classy:normal"
    assert contribs[0].source == FrogEffect.CLASSY_ROLE.key
    assert rest.added_roles == [
        (123, _REACTION_DEV_ROLE, "classy frog role effect")
    ]
    member = await bot.rest.fetch_member(bot.config.guild_id, 123)
    assert member.role_ids == {_REACTION_DEV_ROLE}


async def test_role_converger_removes_role_on_expiry_or_clear(
    full_bot: CazzuBot,
) -> None:
    """Expiry or explicit clear leaves the world converged (role removed)."""
    bot = full_bot
    # full_bot boots with the development guild kind (Config default)
    known = frozenset({_REACTION_DEV_ROLE, _REACTION_PROD_ROLE})
    converger = RoleConverger(known)
    rest = rest_of(bot)
    bot.effects.register_converger(FrogSeam.CLASSY_ROLE, converger)
    target = FakeMember(id=123, name="tester")
    rest.members[(bot.config.guild_id, 123)] = target

    now = pendulum.now("UTC")
    payload = RolePayload(
        role_dev=_REACTION_DEV_ROLE,
        role_prod=_REACTION_PROD_ROLE,
        duration=pendulum.duration(hours=3),
    )
    scope = Scope.member(123)
    reason = "classy frog role effect"

    async def consume() -> None:
        await EffectKey.ROLE.value.consume(
            bot,
            payload,
            scope=scope,
            provenance="frog:classy:normal",
            amount=1,
            now=now,
        )

    # expiry path: a past read prunes the row, then the converger reverts
    await consume()
    member = await bot.rest.fetch_member(bot.config.guild_id, 123)
    assert _REACTION_DEV_ROLE in member.role_ids
    assert (
        await bot.effects.list(
            scope, FrogSeam.CLASSY_ROLE, now=now.add(hours=4)
        )
        == []
    )
    await converger(bot, scope, FrogSeam.CLASSY_ROLE.key)
    member = await bot.rest.fetch_member(bot.config.guild_id, 123)
    assert member.role_ids == set()
    assert rest.removed_roles == [(123, _REACTION_DEV_ROLE, reason)]

    # clear path: a fresh publish, then explicit termination + revert
    await consume()
    member = await bot.rest.fetch_member(bot.config.guild_id, 123)
    assert _REACTION_DEV_ROLE in member.role_ids
    await bot.effects.clear(
        scope, FrogSeam.CLASSY_ROLE, FrogEffect.CLASSY_ROLE.key
    )
    await converger(bot, scope, FrogSeam.CLASSY_ROLE.key)
    member = await bot.rest.fetch_member(bot.config.guild_id, 123)
    assert member.role_ids == set()


async def test_role_converger_is_idempotent_and_only_removes_known(
    full_bot: CazzuBot,
) -> None:
    """Re-converging is a no-op and foreign roles are never touched."""
    bot = full_bot
    # full_bot boots with the development guild kind (Config default)
    known = frozenset({_REACTION_DEV_ROLE, _REACTION_PROD_ROLE})
    converger = RoleConverger(known)
    rest = rest_of(bot)
    bot.effects.register_converger(FrogSeam.CLASSY_ROLE, converger)
    foreign = FakeRole(id=987654, name="some other role")
    target = FakeMember(id=123, name="tester", roles=[foreign])
    rest.members[(bot.config.guild_id, 123)] = target

    payload = RolePayload(
        role_dev=_REACTION_DEV_ROLE,
        role_prod=_REACTION_PROD_ROLE,
        duration=pendulum.duration(hours=3),
    )
    scope = Scope.member(123)
    await EffectKey.ROLE.value.consume(
        bot,
        payload,
        scope=scope,
        provenance="frog:classy:normal",
        amount=1,
        now=pendulum.now("UTC"),
    )
    await converger(bot, scope, FrogSeam.CLASSY_ROLE.key)
    await converger(bot, scope, FrogSeam.CLASSY_ROLE.key)
    member = await bot.rest.fetch_member(bot.config.guild_id, 123)
    assert member.role_ids == {_REACTION_DEV_ROLE, 987654}
    # idempotent re-converges added nothing
    assert rest.added_roles == [
        (123, _REACTION_DEV_ROLE, "classy frog role effect")
    ]

    # after expiry only the seam's known role is removed, foreign stays
    await bot.effects.list(
        scope, FrogSeam.CLASSY_ROLE, now=pendulum.now("UTC").add(hours=4)
    )
    await converger(bot, scope, FrogSeam.CLASSY_ROLE.key)
    member = await bot.rest.fetch_member(bot.config.guild_id, 123)
    assert member.role_ids == {987654}
    assert rest.removed_roles == [
        (123, _REACTION_DEV_ROLE, "classy frog role effect")
    ]
