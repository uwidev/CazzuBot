"""Effects seam store — scope-aware persistent contributions, pulled by features.

Replaces the old ``member_effect`` scalar store with a generic **seam /
contribution / pull** model (see ``docs/needs-rewrite/EFFECTS.md``):
features declare a typed :class:`SeamKey` (an input point on their own
calculator — "message exp", "spawn interval", "react chance"); publishers
record :class:`EffectContribution` rows ("source S published value V into
seam K, effective for target X until E"); the feature's **pull** reads its
seam's active rows and computes whatever it wants. The store never
interprets payloads and never computes formulas.

Scopes: a contribution targets one **member** (``Scope.member(uid)``) or
the **guild** (``Scope.guild(gid)`` — world modifiers like spawn cadence).

Lazy data expiry: a past ``expires_at`` reads as absent and prunes the
row — no sweeper, no scheduler (the row is the truth for its own
question). World-side consequences are a separate mechanism: seams whose
consequence touches Discord carry ``external=True`` and get a scheduled
**convergence job** at ``expires_at`` through ``bot.effects`` (apply
immediately on publish, revert idempotently on fire; ``EffectsClearedEvent``
for the instant revert on explicit clear/clear_scope). The store stays
dumb; convergence logic is feature code.

Naming note: this core module is the *persistent contributions store*;
``plugins/frogs/effects.py`` is the species-side *instant catch/consume
handler registry*. Both are "effects" in different senses.

Call graph (per the self-documenting rule): features' pulls call
:func:`product`/:func:`total`/:func:`list` (experience's ``award_exp`` is
the first consumer); publishers call :func:`publish` — module-level for
pure store writes, ``Effects.publish`` when the seam is external (it
applies the consequence and schedules). ``Effects`` emits
:class:`EffectsClearedEvent` after explicit ``clear``/``clear_scope`` of
external seams; the scheduler dispatches the engine tag to
``Effects._on_converge_due``, which routes to each seam's registered
converger.

Depends on: ``db`` (the table) and ``scheduler`` (the convergence tag).
"""

from __future__ import annotations

import builtins
import logging
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING, Protocol

import pendulum

from cazzubot.db import Database, dump_json

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Any

    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)

_SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS effect_contribution (
		scope_kind TEXT NOT NULL,      -- 'member' | 'guild'
		scope_id   INTEGER NOT NULL,   -- uid, or guild id
		seam       TEXT NOT NULL,      -- derived from a typed SeamKey
		source     TEXT NOT NULL,      -- what published this (e.g. a frog item_id)
		payload    TEXT NOT NULL,      -- JSON blob; interpreted only by the seam's pull
		expires_at TEXT,               -- NULL = permanent; lazy expiry + prune on read
		PRIMARY KEY (scope_kind, scope_id, seam, source)
	)
	""",
]

# Public alias for tooling that needs the DDL without instantiating the class.
SCHEMA = _SCHEMA

# The one scheduler tag every external seam's convergence job rides; the
# engine dispatches rows to the seam's registered converger by payload.
EFFECT_CONVERGE_TAG = "effect.converge"


class ScopeKind(Enum):
    """What a contribution targets — a per-member scope or the guild."""

    MEMBER = "member"
    GUILD = "guild"


@dataclass(frozen=True, slots=True)
class Scope:
    """A contribution target: one member (``uid``) or the whole guild.

    ``kind`` and ``id`` are a single unit — build scopes through
    :meth:`member` / :meth:`guild` so the two can never disagree.
    """

    kind: ScopeKind
    id: int

    @classmethod
    def member(cls, uid: int) -> Scope:
        """A per-member scope (``scope_id`` = the member id)."""
        return cls(ScopeKind.MEMBER, uid)

    @classmethod
    def guild(cls, gid: int) -> Scope:
        """The world scope (``scope_id`` = the guild id)."""
        return cls(ScopeKind.GUILD, gid)


class SeamKey(Protocol):
    """A typed seam identity (mirrors ``InventoryKey``).

    Implementations expose ``key`` — the derived storage string — plus
    ``external``, whether the seam's consequence touches Discord (only
    external seams get convergence jobs). Callers pass the typed object
    (usually an enum member); the store only ever sees derived strings.
    """

    @property
    def key(self) -> str:
        """The derived storage string for this seam."""
        ...

    @property
    def external(self) -> bool:
        """True when the seam needs world-convergence (a Discord side effect)."""
        ...


@dataclass(slots=True)
class EffectContribution:
    """One ``effect_contribution`` row — the recipe, not the consequence."""

    scope_kind: ScopeKind
    scope_id: int
    seam: str
    source: str
    payload: dict[str, object]
    expires_at: pendulum.DateTime | None


class ReapplyPolicy(Enum):
    """What a re-publish of an already-live contribution does (publisher's choice)."""

    EXTEND = "extend"  # keep value, roll expires_at forward additively
    REPLACE = (
        "replace"  # overwrite payload + expiry (legacy set() semantics)
    )
    STACK = "stack"  # parked: future "stronger" stacking arrives as this member


@dataclass(frozen=True, slots=True)
class EffectsClearedEvent:
    """External effect rows were explicitly cleared (not expired).

    Emitted by ``Effects.clear``/``clear_scope`` after the row deletion, so
    subscribers with external seams revert their world consequence
    **instantly** instead of waiting for the scheduled convergence job.
    Subscribers match on ``scope`` and — when not a whole-scope cleanse —
    the exact ``seam``/``source`` they own.

    Call graph: sole emitter is the ``Effects`` service (``bot.effects``);
    observed by every feature with an external seam via ``bot.events.on``.
    """

    scope: Scope
    seam: str | None = None  # None = whole scope (clear_scope)
    source: str | None = None  # None = whole scope (clear_scope)


async def publish(
    db: Database,
    scope: Scope,
    seam: str | SeamKey,
    source: str,
    payload: dict[str, object],
    *,
    duration: timedelta | None = None,
    policy: ReapplyPolicy = ReapplyPolicy.EXTEND,
    now: pendulum.DateTime | None = None,
) -> pendulum.DateTime | None:
    """Record one contribution and return its resulting ``expires_at``.

    ``duration=None`` publishes a **permanent** row (``expires_at`` NULL).
    ``policy`` decides what a re-publish of a live ``(scope, seam, source)``
    does — see :class:`ReapplyPolicy`. An already-expired row is pruned and
    a fresh one written (``now + duration``). This is the **pure store
    write**: external seams need ``Effects.publish`` (the bot-bound
    service) for the consequence + scheduled convergence. ``now`` is
    injected for tests.
    """
    now = now or pendulum.now("UTC")
    seam_key = _key(seam)
    if policy is ReapplyPolicy.STACK:
        raise NotImplementedError(
            "ReapplyPolicy.STACK is parked — not implemented yet"
        )
    fresh_expires = _add_duration(now, duration)
    existing = await fetch(db, scope, seam_key, source, now=now)
    if existing is None:
        # fresh row (or an expired one just pruned by fetch): new payload
        await db.execute(
            """
			INSERT INTO effect_contribution
				(scope_kind, scope_id, seam, source, payload, expires_at)
			VALUES (?, ?, ?, ?, ?, ?)
			""",
            scope.kind.value,
            scope.id,
            seam_key,
            source,
            dump_json(payload),
            _iso(fresh_expires),
        )
        return fresh_expires
    if policy is ReapplyPolicy.REPLACE:
        await db.execute(
            """
			UPDATE effect_contribution
			SET payload = ?, expires_at = ?
			WHERE scope_kind = ? AND scope_id = ? AND seam = ? AND source = ?
			""",
            dump_json(payload),
            _iso(fresh_expires),
            scope.kind.value,
            scope.id,
            seam_key,
            source,
        )
        return fresh_expires
    # EXTEND: keep the value, roll the expiry forward by the new duration.
    # A permanent row stays permanent (there is no expiry to roll).
    expires_at = existing.expires_at
    if existing.expires_at is not None and duration is not None:
        expires_at = existing.expires_at + duration
    await db.execute(
        """
		UPDATE effect_contribution SET expires_at = ?
		WHERE scope_kind = ? AND scope_id = ? AND seam = ? AND source = ?
		""",
        _iso(expires_at),
        scope.kind.value,
        scope.id,
        seam_key,
        source,
    )
    return expires_at


async def list(
    db: Database,
    scope: Scope,
    seam: str | SeamKey,
    *,
    now: pendulum.DateTime | None = None,
) -> builtins.list[EffectContribution]:
    """The seam's active contributions for ``scope``, pruned of expired rows.

    Lazy data expiry: a past ``expires_at`` reads as absent AND deletes
    the row (read-time cleanup, no sweeper). Ordered by ``source`` for
    deterministic pulls. ``now`` is injected for tests.
    """
    now = now or pendulum.now("UTC")
    seam_key = _key(seam)
    contribs = await db.fetch_models(
        EffectContribution,
        "SELECT * FROM effect_contribution"
        + " WHERE scope_kind = ? AND scope_id = ? AND seam = ?"
        + " ORDER BY source",
        scope.kind.value,
        scope.id,
        seam_key,
    )
    active: builtins.list[EffectContribution] = []
    for contrib in contribs:
        if _expired(contrib, now):
            await db.execute(
                """
				DELETE FROM effect_contribution
				WHERE scope_kind = ? AND scope_id = ? AND seam = ? AND source = ?
				""",
                scope.kind.value,
                scope.id,
                seam_key,
                contrib.source,
            )
            continue
        active.append(contrib)
    return active


async def fetch(
    db: Database,
    scope: Scope,
    seam: str | SeamKey,
    source: str,
    *,
    now: pendulum.DateTime | None = None,
) -> EffectContribution | None:
    """One contribution by ``(scope, seam, source)``, or None (prunes expired)."""
    now = now or pendulum.now("UTC")
    seam_key = _key(seam)
    contrib = await db.fetch_model(
        EffectContribution,
        "SELECT * FROM effect_contribution"
        + " WHERE scope_kind = ? AND scope_id = ? AND seam = ? AND source = ?",
        scope.kind.value,
        scope.id,
        seam_key,
        source,
    )
    if contrib is None:
        return None
    if _expired(contrib, now):
        await db.execute(
            """
			DELETE FROM effect_contribution
			WHERE scope_kind = ? AND scope_id = ? AND seam = ? AND source = ?
			""",
            scope.kind.value,
            scope.id,
            seam_key,
            source,
        )
        return None
    return contrib


async def clear(
    db: Database, scope: Scope, seam: str | SeamKey, source: str
) -> None:
    """Delete one contribution (immediate termination — never an expire-mark)."""
    await db.execute(
        """
		DELETE FROM effect_contribution
		WHERE scope_kind = ? AND scope_id = ? AND seam = ? AND source = ?
		""",
        scope.kind.value,
        scope.id,
        _key(seam),
        source,
    )


async def clear_scope(db: Database, scope: Scope) -> None:
    """Delete every **timed** contribution for one whole scope.

    Cross-feature (seam-blind single DELETE); permanent rows
    (``expires_at IS NULL``) survive. External termination also needs the
    ``Effects`` service wrapper to emit :class:`EffectsClearedEvent`.
    """
    await db.execute(
        """
		DELETE FROM effect_contribution
		WHERE scope_kind = ? AND scope_id = ? AND expires_at IS NOT NULL
		""",
        scope.kind.value,
        scope.id,
    )


async def product(
    db: Database,
    scope: Scope,
    seam: str | SeamKey,
    *,
    now: pendulum.DateTime | None = None,
) -> float:
    """Numeric convenience: the product of every active ``value``, 1.0 when empty.

    Reads the numeric-seam convention — each contribution's payload
    carries a ``value`` key (contributions without one count as identity).
    Never chooses order; a pull with a complex formula ignores this and
    does its own math.
    """
    value = 1.0
    for contrib in await list(db, scope, seam, now=now):
        value *= _numeric_value(contrib, 1.0)
    return value


async def total(
    db: Database,
    scope: Scope,
    seam: str | SeamKey,
    *,
    now: pendulum.DateTime | None = None,
) -> float:
    """Numeric convenience: the sum of every active ``value``, 0 when empty.

    Same numeric-seam convention as :func:`product` (contributions without
    a ``value`` key add nothing).
    """
    return sum(
        _numeric_value(contrib, 0.0)
        for contrib in await list(db, scope, seam, now=now)
    )


def _key(seam: str | SeamKey) -> str:
    """The stored seam string for a typed key or a bare key."""
    return seam if isinstance(seam, str) else seam.key


def _iso(value: pendulum.DateTime | None) -> str | None:
    """ISO-8601 UTC storage text, or None for permanent rows."""
    return value.isoformat() if value is not None else None


def _add_duration(
    now: pendulum.DateTime, duration: timedelta | None
) -> pendulum.DateTime | None:
    """``now + duration``, or None for a permanent row."""
    return now + duration if duration is not None else None


def _numeric_value(contrib: EffectContribution, default: float) -> float:
    """A contribution's numeric ``value``, or ``default`` when absent.

    The numeric-seam convention: what :func:`product`/:func:`total` fold.
    Non-numeric payloads (no ``value`` key, or a non-number) fall back to
    the fold's identity (1.0 for product, 0.0 for total). The isinstance
    gate narrows the JSON value to a number before the float conversion.
    """
    value = contrib.payload.get("value", default)
    if not isinstance(value, (int, float)):
        return default
    return float(value)


def _expired(contrib: EffectContribution, now: pendulum.DateTime) -> bool:
    """True when a timed contribution's ``expires_at`` has passed."""
    return contrib.expires_at is not None and contrib.expires_at <= now


class Effects:
    """The effects service on the bot (``bot.effects``).

    Owns the schema (run at boot like settings/scheduler/inventory) and
    delegates the store operations against ``bot.db`` for consumers that
    hold the bot rather than a Database. Beyond the pure store, this is
    the **engine** of the reconciliation rule (see the module docstring):
    it tracks external seams structurally, applies their consequences at
    publish time, schedules convergence jobs at expiry, and emits
    :class:`EffectsClearedEvent` on explicit termination.
    """

    schema = _SCHEMA

    def __init__(self, bot: "CazzuBot") -> None:
        """Bind the service and register the convergence job dispatcher.

        Every external seam's expiry job rides the one engine tag
        (``EFFECT_CONVERGE_TAG``), routed by payload to the seam's
        registered converger. The scheduler's default retry policy applies
        (infinite backoff), so a world-convergence failure is retried —
        the same guarantee mutes have.
        """
        self.bot = bot
        self._convergers: dict[str, Converger] = {}
        self.bot.scheduler.register(
            EFFECT_CONVERGE_TAG, self._on_converge_due
        )

    # -- convergence registry -------------------------------------------

    def register_converger(
        self, seam: SeamKey, handler: Converger
    ) -> None:
        """Register the feature's world-convergence handler for ``seam``.

        Called by the feature that owns ``seam`` during its ``on_load``.
        The handler is **feature code**: it reads the seam's active
        contributions itself, diffs against the member's actual world
        state, and applies/reverts idempotently. Internal seams (no world
        consequence) are meaningless to register — rejected.
        """
        if not seam.external:
            raise ValueError(
                f"seam {seam.key!r} is internal — no world to converge"
            )
        self._convergers[seam.key] = handler
        _log.info("convergence handler registered for seam %r", seam.key)

    def unregister_converger(self, seam: SeamKey) -> None:
        """Drop a convergence registration (the undo of ``register_converger``).

        Defer this to the lifecycle at plugin load so an unload withdraws
        the feature's convergence interest with its other effects.
        """
        self._convergers.pop(seam.key, None)

    # -- engine behavior -------------------------------------------------

    async def publish(
        self,
        scope: Scope,
        seam: SeamKey,
        source: str,
        payload: dict[str, object],
        *,
        duration: timedelta | None = None,
        policy: ReapplyPolicy = ReapplyPolicy.EXTEND,
        now: pendulum.DateTime | None = None,
    ) -> None:
        """Record a contribution, then reconcile the world for external seams.

        Store write first (same policy semantics as the module-level
        :func:`publish`); for an **external** seam the consequence is
        applied at once (the converger runs synchronously) and a
        convergence job is scheduled on the central scheduler at
        ``expires_at`` — so termination reverts even through the scheduler
        alone. Internal seams get neither (no consequence, no job).
        """
        if not seam.external:
            await publish(
                self.bot.db,
                scope,
                seam,
                source,
                payload,
                duration=duration,
                policy=policy,
                now=now,
            )
            return
        handler = self._convergers.get(seam.key)
        if handler is None:
            # fail fast BEFORE the write: a publish that cannot converge
            # is a programming error, not a row to half-reconcile
            raise KeyError(
                "no convergence handler registered for external seam "
                + f"{seam.key!r} — register one with register_converger"
            )
        expires_at = await publish(
            self.bot.db,
            scope,
            seam,
            source,
            payload,
            duration=duration,
            policy=policy,
            now=now,
        )
        await handler(self.bot, scope, seam.key)
        if expires_at is not None:
            await self.bot.scheduler.add(
                EFFECT_CONVERGE_TAG,
                expires_at,
                _job_payload(scope, seam.key, source),
            )

    async def clear(
        self, scope: Scope, seam: SeamKey, source: str
    ) -> None:
        """Delete one contribution; external seams emit EffectsClearedEvent.

        Termination **deletes** the row (never an expire-at-now tombstone);
        the event makes an external seam's world consequence revert
        instantly instead of waiting for the scheduled job.
        """
        await clear(self.bot.db, scope, seam, source)
        if seam.external:
            await self.bot.events.emit(
                EffectsClearedEvent(
                    scope=scope, seam=seam.key, source=source
                )
            )

    async def clear_scope(self, scope: Scope) -> None:
        """Cleanse one whole scope (timed contributions only) + revert event.

        Cross-feature and seam-blind (every seam for the target, one
        DELETE); permanent rows survive. Emits :class:`EffectsClearedEvent`
        with ``seam``/``source`` None so subscribers revert what the
        cleanse removed.
        """
        await clear_scope(self.bot.db, scope)
        await self.bot.events.emit(EffectsClearedEvent(scope=scope))

    # -- pure store delegates ----------------------------------------------

    async def list(
        self,
        scope: Scope,
        seam: SeamKey,
        *,
        now: pendulum.DateTime | None = None,
    ) -> builtins.list[EffectContribution]:
        """A seam's active contributions for ``scope`` (pruned of expired)."""
        return await list(self.bot.db, scope, seam, now=now)

    async def fetch(
        self,
        scope: Scope,
        seam: SeamKey,
        source: str,
        *,
        now: pendulum.DateTime | None = None,
    ) -> EffectContribution | None:
        """One contribution by ``(scope, seam, source)``, or None."""
        return await fetch(self.bot.db, scope, seam, source, now=now)

    async def product(
        self,
        scope: Scope,
        seam: SeamKey,
        *,
        now: pendulum.DateTime | None = None,
    ) -> float:
        """Numeric convenience: product of active ``value``s, 1.0 when empty."""
        return await product(self.bot.db, scope, seam, now=now)

    async def total(
        self,
        scope: Scope,
        seam: SeamKey,
        *,
        now: pendulum.DateTime | None = None,
    ) -> float:
        """Numeric convenience: sum of active ``value``s, 0 when empty."""
        return await total(self.bot.db, scope, seam, now=now)

    # -- engine dispatcher ------------------------------------------------

    async def _on_converge_due(
        self, bot: "CazzuBot", payload: dict[str, Any]
    ) -> None:
        """The convergence job dispatcher (scheduler tag EFFECT_CONVERGE_TAG).

        Invoked by the scheduler when an external seam's expiry job fires,
        with the payload scheduled at publish
        (``scope_kind``/``scope_id``/``seam``/``source``). The job
        **re-evaluates**: an EXTEND that rolled the contribution past this
        fire time keeps it active and re-arms at the new expiry; anything
        else (expired, cleared) converges — the registered handler reads
        the DB and reverts idempotently, so a stale job after termination
        is a no-op. Jobs are never cancelled — a redundant one is never
        wrong.
        """
        scope = Scope(
            ScopeKind(payload["scope_kind"]), payload["scope_id"]
        )
        seam = payload["seam"]
        source = payload["source"]
        handler = self._convergers.get(seam)
        if handler is None:
            # orphan job (its feature unloaded): resolve harmlessly — the
            # contribution row stays the truth for any pull
            _log.warning(
                "no convergence handler for seam %r — dropping job", seam
            )
            return
        contribution = await fetch(bot.db, scope, seam, source)
        if (
            contribution is not None
            and contribution.expires_at is not None
        ):
            # EXTEND rolled the row past the fire time — still active, re-arm
            await bot.scheduler.add(
                EFFECT_CONVERGE_TAG, contribution.expires_at, payload
            )
            return
        await handler(bot, scope, seam)


def _job_payload(
    scope: Scope, seam: str, source: str
) -> dict[str, object]:
    """The scheduler payload for one convergence job (retry-enabled)."""
    return {
        "retry": True,
        "scope_kind": scope.kind.value,
        "scope_id": scope.id,
        "seam": seam,
        "source": source,
    }


if TYPE_CHECKING:
    Converger = Callable[["CazzuBot", Scope, str], Awaitable[None]]
