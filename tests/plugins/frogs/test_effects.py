"""Frog effects — enum-as-registry, dispatch contract, exp effect."""

from __future__ import annotations

from typing import Any, cast

import pendulum
import pytest

from cazzubot.bot import CazzuBot
from cazzubot.models import FrogState, FrogItemKey
from plugins.experience import db as exp_db
from plugins.frogs import db as frog_db
from plugins.frogs import factory
from plugins.frogs.assets import FrogAsset
from plugins.frogs.effects import EffectKey, ExpPayload
from plugins.frogs.events import FrogConsumedEvent
from plugins.frogs.items import FrogItems
from plugins.frogs.species import SPECIES, Species
from tests.fakes import (
    FakeInteraction,
    FakeMember,
    FakeMenuContext,
    menu_button,
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


async def test_exp_effect_grants_payload_values(bot: CazzuBot) -> None:
    """Reusable effect: the same handler, different payload values."""
    effect = EffectKey.EXP.value
    now = pendulum.now("UTC")
    payload = ExpPayload(exp=20, frozen_exp=6)

    await effect.consume(
        bot,
        payload,
        uid=_UID,
        species_key=FrogItemKey.BASIC,
        amount=2,
        state=FrogState.NORMAL,
        now=now,
    )
    assert (
        await exp_db.seasonal_exp(
            bot.db, _UID, now.year, (now.month - 1) // 3
        )
        == 40
    )  # 20 exp/frog * 2

    await effect.consume(
        bot,
        payload,
        uid=_UID,
        species_key=FrogItemKey.BASIC,
        amount=1,
        state=FrogState.FROZEN,
        now=now,
    )
    assert (
        await exp_db.seasonal_exp(
            bot.db, _UID, now.year, (now.month - 1) // 3
        )
        == 46
    )  # +6 frozen


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
            uid=_UID,
            species_key=FrogItemKey.BASIC,
            amount=1,
            state=FrogState.NORMAL,
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
