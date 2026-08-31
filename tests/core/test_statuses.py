"""Statuses seam store — unit + integration through the booted bot.

Unit half drives the module-level store functions against a bare
``Database`` with injected ``now`` (EXTEND/REPLACE policy, lazy expiry,
scope isolation, numeric conveniences, JSON payloads, termination).

Integration half drives the engine on a booted ``CazzuBot`` (``bot.statuses``
+ real scheduler/event bus) with a **fake external seam** whose converger
touches an in-memory consequence: publish applies it and schedules a
convergence job at ``expires_at``, the job reverts idempotently, internal
seams never schedule, and ``StatusesClearedEvent`` reverts synchronously.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

import pendulum
import pytest

from cazzubot import statuses
from cazzubot.bot import CazzuBot
from cazzubot.db import Database
from cazzubot.statuses import (
    STATUS_CONVERGE_TAG,
    StatusesClearedEvent,
    ReapplyPolicy,
    SCHEMA,
    Scope,
)

# the fake external seam's consequence: scope.id -> world flag
RoleState = dict[int, bool]


@dataclass(frozen=True, slots=True)
class FakeSeam:
    """A typed test seam (the SeamKey shape: key + external flag)."""

    key: str = "fake"
    external: bool = False


ROLE_SEAM = FakeSeam(key="fake_role", external=True)
INTERNAL_SEAM = FakeSeam(key="fake_exp", external=False)


@pytest.fixture
async def statuses_db(db: Database) -> Database:
    """A bare Database carrying the status_contribution schema."""
    await db.run_schema(SCHEMA)
    return db


async def _converger(
    state: RoleState,
) -> tuple[
    Callable[[CazzuBot, Scope, str], Awaitable[None]],
    list[tuple[str, int]],
]:
    """A fake feature converger: applies while any row is active, else reverts.

    Idempotent by construction (the DB is the only authority — the world
    flag is re-derived on every call). Logs only **actual mutations**
    (``("apply", scope_id)`` / ``("revert", scope_id)``) so a double-run
    shows the revert happened exactly once.
    """

    calls: list[tuple[str, int]] = []

    async def converge(bot: CazzuBot, scope: Scope, seam: str) -> None:
        active = await statuses.list(bot.db, scope, seam)
        if active:
            if scope.id not in state:
                state[scope.id] = True
                calls.append(("apply", scope.id))
        elif scope.id in state:
            del state[scope.id]
            calls.append(("revert", scope.id))

    return converge, calls


# -- store: policies -----------------------------------------------------


async def test_extend_rolls_expiry_additively_and_keeps_value(
    statuses_db: Database,
) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = FakeSeam()
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 2.0},
        duration=timedelta(hours=1),
        now=now,
    )
    # re-publish 30m later with a DIFFERENT payload: EXTEND keeps the value
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 99.0},
        duration=timedelta(hours=1),
        now=now.add(minutes=30),
    )
    rows = await statuses.list(
        statuses_db, Scope.member(1), seam, now=now.add(minutes=30)
    )
    assert len(rows) == 1  # two publishes -> one row
    assert rows[0].payload == {"value": 2.0}  # value unchanged
    # expiry rolled additively: first publish + 2 x duration
    assert rows[0].expires_at == now.add(hours=2)


async def test_replace_overwrites_payload_and_expiry(
    statuses_db: Database,
) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = FakeSeam()
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 1.5},
        duration=timedelta(hours=1),
        now=now,
    )
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 5.0},
        duration=timedelta(minutes=30),
        policy=ReapplyPolicy.REPLACE,
        now=now.add(minutes=15),
    )
    rows = await statuses.list(
        statuses_db, Scope.member(1), seam, now=now.add(minutes=15)
    )
    assert len(rows) == 1
    assert rows[0].payload == {"value": 5.0}
    assert rows[0].expires_at == now.add(minutes=45)  # 15 + 30


async def test_expired_row_pruned_then_fresh_row_written(
    statuses_db: Database,
) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = FakeSeam()
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 2.0},
        duration=timedelta(hours=1),
        now=now,
    )
    later = now.add(hours=2)  # past the row's expiry
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 3.0},
        duration=timedelta(hours=1),
        now=later,
    )
    rows = await statuses.list(
        statuses_db, Scope.member(1), seam, now=later
    )
    assert len(rows) == 1
    assert rows[0].payload == {
        "value": 3.0
    }  # fresh write takes the new payload
    assert rows[0].expires_at == later.add(hours=1)


async def test_stack_policy_is_parked(statuses_db: Database) -> None:
    with pytest.raises(NotImplementedError):
        await statuses.publish(
            statuses_db,
            Scope.member(1),
            FakeSeam(),
            "src",
            {"value": 2.0},
            duration=timedelta(hours=1),
            policy=ReapplyPolicy.STACK,
        )


# -- store: lazy expiry + scope isolation ----------------------------------


async def test_lazy_expiry_reads_absent_and_prunes(
    statuses_db: Database,
) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = FakeSeam()
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 2.0},
        duration=timedelta(minutes=5),
        now=now,
    )
    # before expiry: present
    assert (
        await statuses.list(statuses_db, Scope.member(1), seam, now=now)
        != []
    )
    # after expiry: reads as absent AND the row is pruned
    later = now.add(minutes=6)
    assert (
        await statuses.list(statuses_db, Scope.member(1), seam, now=later)
        == []
    )
    assert (
        await statuses_db.fetchval(
            "SELECT COUNT(*) FROM status_contribution"
        )
        == 0
    )


async def test_permanent_row_never_expires(statuses_db: Database) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = FakeSeam()
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 1.25},
        duration=None,
        now=now,
    )
    rows = await statuses.list(
        statuses_db, Scope.member(1), seam, now=now.add(years=1)
    )
    assert len(rows) == 1
    assert rows[0].expires_at is None


async def test_scopes_are_isolated(statuses_db: Database) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = FakeSeam()
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 2.0},
        duration=timedelta(hours=1),
        now=now,
    )
    # same seam: member 2 and the guild see nothing
    assert (
        await statuses.list(statuses_db, Scope.member(2), seam, now=now)
        == []
    )
    assert (
        await statuses.list(statuses_db, Scope.guild(1), seam, now=now)
        == []
    )
    # a different source on the same scope stacks as a separate contribution
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "other",
        {"value": 3.0},
        duration=timedelta(hours=1),
        now=now,
    )
    assert (
        len(
            await statuses.list(
                statuses_db, Scope.member(1), seam, now=now
            )
        )
        == 2
    )


# -- store: numeric conveniences + payloads --------------------------------


async def test_product_and_total_defaults(statuses_db: Database) -> None:
    seam = FakeSeam()
    scope = Scope.member(1)
    assert await statuses.product(statuses_db, scope, seam) == 1.0
    assert await statuses.total(statuses_db, scope, seam) == 0.0
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    await statuses.publish(
        statuses_db,
        scope,
        seam,
        "a",
        {"value": 2.0},
        duration=timedelta(hours=1),
        now=now,
    )
    await statuses.publish(
        statuses_db,
        scope,
        seam,
        "b",
        {"value": 3.0},
        duration=timedelta(hours=1),
        now=now,
    )
    assert await statuses.product(statuses_db, scope, seam, now=now) == 6.0
    assert await statuses.total(statuses_db, scope, seam, now=now) == 5.0


async def test_product_ignores_expired_contributions(
    statuses_db: Database,
) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = FakeSeam()
    scope = Scope.member(1)
    await statuses.publish(
        statuses_db,
        scope,
        seam,
        "short",
        {"value": 2.0},
        duration=timedelta(minutes=5),
        now=now,
    )
    await statuses.publish(
        statuses_db,
        scope,
        seam,
        "long",
        {"value": 4.0},
        duration=timedelta(hours=1),
        now=now,
    )
    later = now.add(minutes=6)
    assert (
        await statuses.product(statuses_db, scope, seam, now=later) == 4.0
    )
    assert await statuses.total(statuses_db, scope, seam, now=later) == 4.0


async def test_json_payload_round_trips(statuses_db: Database) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = FakeSeam()
    payload: dict[str, object] = {
        "op": "mult",
        "value": 2.0,
        "nested": {"tags": ["a", "b"], "n": 3},
    }
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "src",
        payload,
        duration=timedelta(hours=1),
        now=now,
    )
    rows = await statuses.fetch(
        statuses_db, Scope.member(1), seam, "src", now=now
    )
    assert rows is not None
    assert rows.payload == payload


# -- store: termination ----------------------------------------------------


async def test_clear_deletes_instead_of_expiring(
    statuses_db: Database,
) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = FakeSeam()
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "src",
        {"value": 2.0},
        duration=timedelta(hours=1),
        now=now,
    )
    await statuses.clear(statuses_db, Scope.member(1), seam, "src")
    # gone immediately — no read/prune step, no expire-at-now tombstone
    assert (
        await statuses_db.fetchval(
            "SELECT COUNT(*) FROM status_contribution"
        )
        == 0
    )
    assert (
        await statuses.fetch(statuses_db, Scope.member(1), seam, "src")
        is None
    )


async def test_clear_scope_targets_timed_rows_of_one_scope_only(
    statuses_db: Database,
) -> None:
    now = pendulum.datetime(2026, 1, 1, tz="UTC")
    seam = FakeSeam()
    other = FakeSeam(key="fake_other", external=False)
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "a",
        {"value": 1.0},
        duration=timedelta(hours=1),
        now=now,
    )
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        other,
        "b",
        {"value": 2.0},
        duration=timedelta(hours=1),
        now=now,
    )
    await statuses.publish(
        statuses_db,
        Scope.member(1),
        seam,
        "perm",
        {"value": 3.0},
        duration=None,
        now=now,
    )
    await statuses.publish(
        statuses_db,
        Scope.member(2),
        seam,
        "c",
        {"value": 4.0},
        duration=timedelta(hours=1),
        now=now,
    )
    await statuses.publish(
        statuses_db,
        Scope.guild(1),
        seam,
        "d",
        {"value": 5.0},
        duration=timedelta(hours=1),
        now=now,
    )
    await statuses.clear_scope(statuses_db, Scope.member(1))
    # member 1: only the permanent row survives (seam-blind across seams)
    member1 = await statuses.list(
        statuses_db, Scope.member(1), seam, now=now
    )
    assert len(member1) == 1 and member1[0].source == "perm"
    assert (
        await statuses.list(statuses_db, Scope.member(1), other, now=now)
        == []
    )
    # other scopes untouched
    assert (
        len(
            await statuses.list(
                statuses_db, Scope.member(2), seam, now=now
            )
        )
        == 1
    )
    assert (
        len(
            await statuses.list(statuses_db, Scope.guild(1), seam, now=now)
        )
        == 1
    )


# -- integration: the engine (bot.statuses + scheduler + event bus) -----------


async def test_internal_seam_never_schedules(bot: CazzuBot) -> None:
    await bot.statuses.publish(
        Scope.member(1),
        INTERNAL_SEAM,
        "src",
        {"value": 2.0},
        duration=timedelta(hours=1),
    )
    assert await bot.scheduler.get(STATUS_CONVERGE_TAG) == []


async def test_external_publish_applies_and_schedules(
    bot: CazzuBot,
) -> None:
    state: RoleState = {}
    converge, _ = await _converger(state)
    bot.statuses.register_converger(ROLE_SEAM, converge)
    now = pendulum.now("UTC")
    await bot.statuses.publish(
        Scope.member(42),
        ROLE_SEAM,
        "item1",
        {"role_id": 7},
        duration=timedelta(hours=1),
        now=now,
    )
    assert state == {42: True}  # consequence applied at once
    tasks = await bot.scheduler.get(STATUS_CONVERGE_TAG)
    assert len(tasks) == 1
    assert tasks[0].run_at == now.add(hours=1)
    assert tasks[0].payload["scope_kind"] == "member"
    assert tasks[0].payload["scope_id"] == 42
    assert tasks[0].payload["seam"] == "fake_role"
    assert tasks[0].payload["source"] == "item1"


async def test_extend_rearms_the_pending_job(bot: CazzuBot) -> None:
    state: RoleState = {}
    converge, calls = await _converger(state)
    bot.statuses.register_converger(ROLE_SEAM, converge)
    now = pendulum.now("UTC")
    await bot.statuses.publish(
        Scope.member(42),
        ROLE_SEAM,
        "item1",
        {},
        duration=timedelta(hours=1),
        now=now,
    )
    (task,) = await bot.scheduler.get(STATUS_CONVERGE_TAG)
    # an EXTEND rolled the row past the original fire time before it fired:
    # move the expiry forward, then let the stale job fire
    await bot.db.execute(
        "UPDATE status_contribution SET expires_at = ?"
        + " WHERE scope_kind = 'member' AND scope_id = 42"
        + " AND seam = 'fake_role' AND source = 'item1'",
        now.add(hours=3).isoformat(),
    )
    await bot.scheduler.handlers[STATUS_CONVERGE_TAG](bot, task.payload)
    # still active -> re-armed at the new expiry; converger NOT re-invoked
    tasks = await bot.scheduler.get(STATUS_CONVERGE_TAG)
    assert len(tasks) == 2
    assert tasks[-1].run_at == now.add(hours=3)
    assert calls == [("apply", 42)]  # applied once, at publish; no re-run
    assert state == {42: True}


async def test_convergence_job_reverts_idempotently(bot: CazzuBot) -> None:
    state: RoleState = {}
    converge, calls = await _converger(state)
    bot.statuses.register_converger(ROLE_SEAM, converge)
    now = pendulum.now("UTC")
    await bot.statuses.publish(
        Scope.member(42),
        ROLE_SEAM,
        "item1",
        {},
        duration=timedelta(hours=1),
        now=now,
    )
    (task,) = await bot.scheduler.get(STATUS_CONVERGE_TAG)
    # the contribution expires before its job fires: simulate the passage
    # of time, then run the job (and a stale duplicate) directly
    await bot.db.execute(
        "UPDATE status_contribution SET expires_at = ?"
        + " WHERE scope_kind = 'member' AND scope_id = 42"
        + " AND seam = 'fake_role' AND source = 'item1'",
        now.subtract(minutes=1).isoformat(),
    )
    handler = bot.scheduler.handlers[STATUS_CONVERGE_TAG]
    await handler(bot, task.payload)
    assert state == {}  # reverted
    await handler(
        bot, task.payload
    )  # double-run: still reverted, no repeat
    assert state == {}
    # exactly one apply (at publish) and one revert (the first job run) —
    # the second run re-derived the same (empty) world and changed nothing
    assert calls == [("apply", 42), ("revert", 42)]
    assert (
        await bot.db.fetchval("SELECT COUNT(*) FROM status_contribution")
        == 0
    )


async def test_clear_emits_event_and_terminal_job_is_a_noop(
    bot: CazzuBot,
) -> None:
    state: RoleState = {}
    converge, calls = await _converger(state)
    bot.statuses.register_converger(ROLE_SEAM, converge)

    async def on_cleared(event: StatusesClearedEvent) -> None:
        if event.seam is None or event.seam == ROLE_SEAM.key:
            await converge(bot, event.scope, ROLE_SEAM.key)

    bot.events.on(StatusesClearedEvent, on_cleared)
    now = pendulum.now("UTC")
    await bot.statuses.publish(
        Scope.member(42),
        ROLE_SEAM,
        "item1",
        {},
        duration=timedelta(hours=1),
        now=now,
    )
    assert state == {42: True}
    tasks = await bot.scheduler.get(STATUS_CONVERGE_TAG)
    assert len(tasks) == 1

    await bot.statuses.clear(Scope.member(42), ROLE_SEAM, "item1")

    # termination deletes the row (no tombstone) and reverts instantly
    assert (
        await bot.db.fetchval("SELECT COUNT(*) FROM status_contribution")
        == 0
    )
    assert state == {}
    # the revert rode the event, synchronously — the apply (publish) and
    # the clear's revert are the only world mutations
    assert calls == [("apply", 42), ("revert", 42)]
    # the stale scheduled job still fires later: fetch sees nothing active,
    # the converger no-ops, and no re-arm happens
    await bot.scheduler.handlers[STATUS_CONVERGE_TAG](
        bot, tasks[0].payload
    )
    assert state == {}
    assert calls == [("apply", 42), ("revert", 42)]
    assert len(await bot.scheduler.get(STATUS_CONVERGE_TAG)) == 1


async def test_clear_scope_reverts_synchronously(bot: CazzuBot) -> None:
    state: RoleState = {}
    converge, _ = await _converger(state)
    bot.statuses.register_converger(ROLE_SEAM, converge)

    async def on_cleared(event: StatusesClearedEvent) -> None:
        if event.seam is None or event.seam == ROLE_SEAM.key:
            await converge(bot, event.scope, ROLE_SEAM.key)

    bot.events.on(StatusesClearedEvent, on_cleared)
    now = pendulum.now("UTC")
    await bot.statuses.publish(
        Scope.member(42),
        ROLE_SEAM,
        "item1",
        {},
        duration=timedelta(hours=1),
        now=now,
    )
    await bot.statuses.publish(
        Scope.member(7),
        ROLE_SEAM,
        "item1",
        {},
        duration=timedelta(hours=1),
        now=now,
    )
    assert state == {7: True, 42: True}

    await bot.statuses.clear_scope(Scope.member(42))

    # one target only, reverted synchronously via the event (no scheduler)
    assert state == {7: True}
    assert (
        await statuses.list(bot.db, Scope.member(42), ROLE_SEAM, now=now)
        == []
    )
    assert (
        len(
            await statuses.list(
                bot.db, Scope.member(7), ROLE_SEAM, now=now
            )
        )
        == 1
    )


async def test_external_publish_without_converger_raises(
    bot: CazzuBot,
) -> None:
    with pytest.raises(KeyError):
        await bot.statuses.publish(
            Scope.member(1),
            ROLE_SEAM,
            "src",
            {},
            duration=timedelta(hours=1),
        )
    # fail-fast: a publish that cannot converge never writes its row
    assert (
        await bot.db.fetchval("SELECT COUNT(*) FROM status_contribution")
        == 0
    )
    assert await bot.scheduler.get(STATUS_CONVERGE_TAG) == []


async def test_registering_internal_seam_converger_rejected(
    bot: CazzuBot,
) -> None:
    with pytest.raises(ValueError):
        bot.statuses.register_converger(
            INTERNAL_SEAM, converge_placeholder
        )


async def converge_placeholder(
    _bot: CazzuBot, _scope: Scope, _seam: str
) -> None:
    """A never-invoked stand-in for the rejected registration test."""
    raise AssertionError("internal seams must never converge")
