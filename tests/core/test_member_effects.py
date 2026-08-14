"""Member effects — typed modifiers with lazy read-time expiry."""

from __future__ import annotations

import pytest
import pendulum

from cazzubot.db import Database
from cazzubot.member_effects import (
    SCHEMA,
    MemberEffectKey,
    clear,
    get,
    set,
)


@pytest.fixture
async def effects_db(db: Database) -> Database:
    await db.run_schema(SCHEMA)
    return db


async def test_set_get_and_clear(effects_db: Database) -> None:
    await set(effects_db, 1, MemberEffectKey.EXP_MULTIPLIER, 2.0)
    assert await get(effects_db, 1, MemberEffectKey.EXP_MULTIPLIER) == 2.0
    # absent key reads as None
    assert await get(effects_db, 2, MemberEffectKey.EXP_MULTIPLIER) is None

    await clear(effects_db, 1, MemberEffectKey.EXP_MULTIPLIER)
    assert await get(effects_db, 1, MemberEffectKey.EXP_MULTIPLIER) is None


async def test_set_overwrites(effects_db: Database) -> None:
    await set(effects_db, 1, MemberEffectKey.EXP_MULTIPLIER, 1.5)
    await set(effects_db, 1, MemberEffectKey.EXP_MULTIPLIER, 3.0)
    assert await get(effects_db, 1, MemberEffectKey.EXP_MULTIPLIER) == 3.0


async def test_expiry_is_lazy_and_prunes(effects_db: Database) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    await set(
        effects_db,
        1,
        MemberEffectKey.EXP_MULTIPLIER,
        2.0,
        expires_at=now.add(minutes=5),
    )
    # before expiry: present
    assert (
        await get(effects_db, 1, MemberEffectKey.EXP_MULTIPLIER, now=now)
        == 2.0
    )
    # after expiry: reads as absent AND the row is pruned
    later = now.add(minutes=6)
    assert (
        await get(effects_db, 1, MemberEffectKey.EXP_MULTIPLIER, now=later)
        is None
    )
    assert (
        await effects_db.fetchval("SELECT COUNT(*) FROM member_effect")
        == 0
    )


async def test_permanent_has_no_expiry(effects_db: Database) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    await set(effects_db, 1, MemberEffectKey.EXP_MULTIPLIER, 1.25)
    assert (
        await get(
            effects_db,
            1,
            MemberEffectKey.EXP_MULTIPLIER,
            now=now.add(years=1),
        )
        == 1.25
    )
