"""Frog items — the exp oracle and the item-owned consume composition.

Phase-1 separation (docs/aegis/plans/2026-08-28-frog-species-handoff.md):
the item composes what consuming does — exp from its oracle, plus the
modifiers it decides to apply. No species composes an effect yet; the
dispatcher test injects one to prove the pipeline.
"""

from __future__ import annotations

from typing import Any

import pendulum
import pytest

from cazzubot.effects import Scope
from cazzubot.models import FrogItemKey, FrogState
from plugins.experience import db as exp_db
from plugins.frogs.effects import EffectKey, ExpPayload
from plugins.frogs.events import FrogConsumedEvent
from plugins.frogs.items import (
    FrogItems,
    _SPECIES_CONSUME,
    _consume_blurb,
)


def test_species_consume_composition_is_basic_only() -> None:
    """Phase 1: no species composes an effect — Basic's tuple is empty."""
    assert set(_SPECIES_CONSUME) == {FrogItemKey.BASIC}
    assert _SPECIES_CONSUME[FrogItemKey.BASIC] == ()


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


async def test_consume_dispatches_composed_modifiers(
    bot: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The composition pipeline applies the item's composed modifiers.

    Production has no composed effect for Basic, so this injects one (an
    ExpPayload — the only modifier in the registry) and spies on its
    handler: consuming a Basic must hand the modifier the member scope,
    the item id as provenance, the amount and the timestamp — then log
    the exp and report :class:`FrogConsumedEvent`.
    """
    calls: list[tuple[object, object]] = []
    seen: list[dict[str, object]] = []
    recorded_now: pendulum.DateTime | None = None

    async def spy_consume(
        bot_: object,
        payload_: object,
        *,
        scope: Scope,
        provenance: str,
        amount: int,
        now: pendulum.DateTime,
    ) -> None:
        nonlocal recorded_now
        calls.append((bot_, payload_))
        recorded_now = now
        seen.append(
            {
                "scope": scope,
                "provenance": provenance,
                "amount": amount,
                "now": now,
            }
        )

    monkeypatch.setattr(EffectKey.EXP.value, "consume", spy_consume)
    monkeypatch.setitem(
        _SPECIES_CONSUME,
        FrogItemKey.BASIC,
        (ExpPayload(exp=10, frozen_exp=3),),
    )

    received: list[FrogConsumedEvent] = []

    async def on_consumed(event: FrogConsumedEvent) -> None:
        received.append(event)

    bot.events.on(FrogConsumedEvent, on_consumed)

    uid = 123
    consume = FrogItems.BASIC.value.consume
    assert consume is not None
    await consume(bot, uid, 1)

    assert len(calls) == 1
    assert calls[0][0] is bot
    assert isinstance(calls[0][1], ExpPayload)
    assert seen[0]["scope"] == Scope.member(uid)
    assert seen[0]["provenance"] == "frog:basic:normal"
    assert seen[0]["amount"] == 1
    assert isinstance(seen[0]["now"], pendulum.DateTime)
    assert isinstance(recorded_now, pendulum.DateTime)

    now = pendulum.now("UTC")
    assert (
        await exp_db.seasonal_exp(bot.db, uid, now.year, (now.month - 1) // 3)
        == 10
    )

    assert len(received) == 1
    assert received[0].uid == uid
    assert received[0].species_key is FrogItemKey.BASIC
    assert received[0].state is FrogState.NORMAL
    assert received[0].amount == 1
    assert received[0].at == recorded_now.isoformat()