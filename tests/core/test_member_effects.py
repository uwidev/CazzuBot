"""Member modifier behaviors — re-expressed through the effects seam store.

The legacy ``member_effect`` store (one scalar per member × key) retired;
these tests pin the OLD behaviors through their new store
(``cazzubot/effects.py``): publish → contribution, numeric pull (product),
REPLACE preserves the old set() overwrite, lazy read-time expiry, and
permanent rows. See ``tests/core/test_effects.py`` for the full store
surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest
import pendulum

from cazzubot import effects
from cazzubot.db import Database
from cazzubot.effects import ReapplyPolicy, SCHEMA, Scope


@dataclass(frozen=True, slots=True)
class ExpSeam:
    """The numeric member seam these tests publish to (SeamKey shape)."""

    key: str = "message_exp_multiplier"
    external: bool = False


@pytest.fixture
async def effects_db(db: Database) -> Database:
    """A bare Database carrying the effect_contribution schema."""
    await db.run_schema(SCHEMA)
    return db


async def test_publish_product_and_clear(effects_db: Database) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = ExpSeam()
    await effects.publish(
        effects_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 2.0},
        duration=None,
        now=now,
    )
    assert (
        await effects.product(effects_db, Scope.member(1), seam, now=now)
        == 2.0
    )
    # absent reads as the identity (1.0), where the old store read None
    assert (
        await effects.product(effects_db, Scope.member(2), seam, now=now)
        == 1.0
    )
    await effects.clear(effects_db, Scope.member(1), seam, "src")
    assert (
        await effects.product(effects_db, Scope.member(1), seam, now=now)
        == 1.0
    )


async def test_reapply_with_replace_preserves_set_semantics(
    effects_db: Database,
) -> None:
    """The old ``set()`` overwrote the value; REPLACE keeps that behavior."""
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = ExpSeam()
    await effects.publish(
        effects_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 1.5},
        duration=None,
        now=now,
    )
    await effects.publish(
        effects_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 3.0},
        duration=None,
        policy=ReapplyPolicy.REPLACE,
        now=now,
    )
    assert (
        await effects.product(effects_db, Scope.member(1), seam, now=now)
        == 3.0
    )
    assert (
        len(await effects.list(effects_db, Scope.member(1), seam, now=now))
        == 1
    )


async def test_expiry_is_lazy_and_prunes(effects_db: Database) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = ExpSeam()
    await effects.publish(
        effects_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 2.0},
        duration=timedelta(minutes=5),
        now=now,
    )
    # before expiry: present
    assert (
        await effects.product(effects_db, Scope.member(1), seam, now=now)
        == 2.0
    )
    # after expiry: reads as absent AND the row is pruned
    later = now.add(minutes=6)
    assert (
        await effects.product(effects_db, Scope.member(1), seam, now=later)
        == 1.0
    )
    assert (
        await effects_db.fetchval(
            "SELECT COUNT(*) FROM effect_contribution"
        )
        == 0
    )


async def test_permanent_has_no_expiry(effects_db: Database) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = ExpSeam()
    await effects.publish(
        effects_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 1.25},
        duration=None,
        now=now,
    )
    rows = await effects.list(
        effects_db, Scope.member(1), seam, now=now.add(years=1)
    )
    assert len(rows) == 1 and rows[0].expires_at is None
