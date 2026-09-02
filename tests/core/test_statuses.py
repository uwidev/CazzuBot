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
    RoleConverger,
    SCHEMA,
    Scope,
    ScopeKind,
    Status,
    register_status,
    status_by_source,
    statuses_for_seam,
)

from tests.fakes import FakeMember, FakeRest, seed_bot

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


# -- stock RoleConverger (role-granting seams) -----------------------------
# The generic role-seam converger is exercised with fake statuses so the
# core contract (structural ``role_id_for(guild_kind)``) is pinned without
# depending on the frogs plugin's RoleStatus.


@dataclass(frozen=True, slots=True, kw_only=True)
class _RoleGrantStatus(Status):
    """A role-granting status: exposes ``role_id_for`` (the core contract)."""

    role_dev: int
    role_prod: int

    def role_id_for(self, guild_kind: str) -> int:
        """The concrete role id for the guild side (dev/prod pair)."""
        return (
            self.role_dev
            if guild_kind == "development"
            else self.role_prod
        )


def _role_status(
    key: str, seam: FakeSeam, role_dev: int
) -> _RoleGrantStatus:
    """A registered role-granting status on ``seam`` for the dev guild."""
    status = _RoleGrantStatus(
        key=key,
        name=key,
        seam=seam,
        role_dev=role_dev,
        role_prod=role_dev + 1,
    )
    register_status(status)
    return status


async def _role_member_bot(
    bot: CazzuBot,
) -> tuple[FakeRest, FakeMember]:
    """Seed the bot's rest fakes with one fetchable member (scope id 123)."""
    rest = FakeRest()
    seed_bot(bot, rest=rest)
    member = FakeMember(id=123, name="tester")
    rest.members[(bot.config.guild_id, 123)] = member
    return rest, member


async def test_role_converger_grants_the_wanted_role(
    bot: CazzuBot,
) -> None:
    """An external publish runs the stock converger; the member gets the role."""
    rest, member = await _role_member_bot(bot)
    seam = FakeSeam(key="prize_role_grant", external=True)
    _role_status("prize:role:gold", seam, 9001)
    converger = RoleConverger(reason="prize role status")
    bot.statuses.register_converger(seam, converger)

    await bot.statuses.publish(
        Scope.member(123),
        seam,
        "prize:role:gold",
        {"from": "prize:gold"},
    )

    assert member.role_ids == {9001}
    assert rest.added_roles == [(123, 9001, "prize role status")]


async def test_role_converger_removes_only_its_own_roles_on_expiry(
    bot: CazzuBot,
) -> None:
    """Revert is idempotent and never touches a foreign role on the member."""
    rest, member = await _role_member_bot(bot)
    member.role_ids.add(987654)  # a role this seam does not own
    seam = FakeSeam(key="prize_role_expiry", external=True)
    role = _role_status("prize:role:gold", seam, 9001)
    converger = RoleConverger(reason="prize role status")
    bot.statuses.register_converger(seam, converger)
    await bot.statuses.publish(
        Scope.member(123),
        seam,
        role.key,
        {"from": "prize:gold"},
    )
    assert member.role_ids == {9001, 987654}

    # the contribution dies (lazy expiry prune, like a read past the window)
    await bot.db.execute(
        "DELETE FROM status_contribution"
        + " WHERE scope_kind = 'member' AND scope_id = 123"
        + " AND seam = ? AND source = ?",
        seam.key,
        role.key,
    )
    await converger(bot, Scope.member(123), seam.key)
    assert member.role_ids == {987654}  # foreign role untouched
    assert rest.removed_roles == [(123, 9001, "prize role status")]
    # idempotent: a stale duplicate run changes nothing
    await converger(bot, Scope.member(123), seam.key)
    assert rest.removed_roles == [(123, 9001, "prize role status")]


async def test_role_converger_folds_siblings_and_ignores_other_statuses(
    bot: CazzuBot,
) -> None:
    """Each active role status is wanted; non-granting statuses never matter."""
    rest, member = await _role_member_bot(bot)
    member.role_ids.add(987654)
    seam = FakeSeam(key="prize_role_siblings", external=True)
    gold = _role_status("prize:role:gold", seam, 9001)
    silver = _role_status("prize:role:silver", seam, 9002)
    not_a_role = _DummyStatus(
        key="prize:role:nope", name="nope", seam=seam
    )  # registered on the seam but not role-granting
    register_status(not_a_role)
    converger = RoleConverger(reason="prize role status")
    bot.statuses.register_converger(seam, converger)

    for role in (gold, silver, not_a_role):
        await bot.statuses.publish(
            Scope.member(123),
            seam,
            role.key,
            {"from": "prize:item"},
        )
    # only the role-granting siblings are wanted — not_a_role grants nothing
    assert member.role_ids == {9001, 9002, 987654}

    # the gold contribution expires: only gold's role is removed — silver
    # stays wanted and the foreign role is untouched
    await bot.db.execute(
        "DELETE FROM status_contribution"
        + " WHERE scope_kind = 'member' AND scope_id = 123"
        + " AND seam = ? AND source = ?",
        seam.key,
        gold.key,
    )
    await converger(bot, Scope.member(123), seam.key)
    assert member.role_ids == {9002, 987654}
    assert rest.removed_roles == [(123, 9001, "prize role status")]

    # everything role-granting gone (not_a_role still active): both roles
    # revert, nothing else is touched
    await bot.db.execute(
        "DELETE FROM status_contribution"
        + " WHERE scope_kind = 'member' AND scope_id = 123"
        + " AND seam = ? AND source = ?",
        seam.key,
        silver.key,
    )
    await converger(bot, Scope.member(123), seam.key)
    assert member.role_ids == {987654}
    assert rest.removed_roles == [
        (123, 9001, "prize role status"),
        (123, 9002, "prize role status"),
    ]


# -- the Status class + registry ------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class _DummyStatus(Status):
    """A test Status subclass carrying an extra value field."""

    duty: int = 1


_DUMMY_SEAM = FakeSeam(key="dummy", external=False)


async def test_status_apply_publishes_provenance_only(
    bot: CazzuBot,
) -> None:
    """apply() records one row: source = the class key, payload = provenance."""
    status = _DummyStatus(
        key="k.1",
        name="x",
        seam=_DUMMY_SEAM,
        duration=timedelta(hours=1),
    )
    await status.apply(
        bot, scope=Scope.member(1), provenance="frog:pog:normal"
    )
    contribs = await bot.statuses.list(Scope.member(1), _DUMMY_SEAM)
    assert contribs and contribs[0].payload == {"from": "frog:pog:normal"}
    assert contribs[0].source == "k.1"


async def test_status_apply_enforces_scope_kind(bot: CazzuBot) -> None:
    """A member-scoped status refuses a guild scope (and vice versa)."""
    status = _DummyStatus(
        key="k.2", name="x", seam=_DUMMY_SEAM, scope_kind=ScopeKind.MEMBER
    )
    with pytest.raises(TypeError, match="member-scoped"):
        await status.apply(bot, scope=Scope.guild(2), provenance="p")


def test_registry_roundtrip_by_source() -> None:
    """register_status / status_by_source are idempotent and key-keyed."""
    s1 = _DummyStatus(key="k.rt", name="rt", seam=_DUMMY_SEAM)
    register_status(s1)
    assert status_by_source("k.rt") is s1
    # re-register replaces (reload-safe)
    s2 = _DummyStatus(key="k.rt", name="rt2", seam=_DUMMY_SEAM)
    register_status(s2)
    assert status_by_source("k.rt") is s2
    assert status_by_source("nope") is None


def test_statuses_for_seam_filters_by_key() -> None:
    """statuses_for_seam returns only the statuses feeding that seam."""
    a = _DummyStatus(key="k.a", name="a", seam=_DUMMY_SEAM)
    other_seam = FakeSeam(key="other", external=False)
    b = _DummyStatus(key="k.b", name="b", seam=other_seam)
    register_status(a)
    register_status(b)
    keys = {s.key for s in statuses_for_seam(_DUMMY_SEAM)}
    assert "k.a" in keys and "k.b" not in keys
