"""Central scheduler for DB-backed delayed tasks.

One loop polls the ``tasks`` table every second and dispatches due rows to
the handler registered for their tag. Handlers re-schedule by inserting new
rows, so tasks survive restarts (mute expiry, frog spawns, counter expiry, …).

Dispatch is concurrent: each due row runs in its own asyncio task (bounded
by a semaphore), so a slow handler never stalls the loop or other tasks.

Tasks resolve by default when due: the fired row is deleted whether or not
the handler raised (v1's contract — "due, handled, gone"). Tasks that need
guaranteed handling opt in via the reserved payload key ``retry: True``;
on handler failure they are kept and re-armed per their tag's ``TaskPolicy``
(backoff, attempt cap) until they succeed or the cap is hit. ``attempt`` is
also reserved (the retry counter). ``TaskPolicy.stale_after`` is the
missed-run rule for rows that came due while the bot was down.

Replaces v1's per-plugin ``@tasks.loop(seconds=1)`` polling of the same
table.
"""

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol, override

import aiosqlite
import hikari
import pendulum

from cazzubot.timeparse import InvalidTimeError, parse_duration

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot
    from cazzubot.plugin import TaskHandler

_log = logging.getLogger(__name__)

_SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS tasks (
		id      INTEGER PRIMARY KEY AUTOINCREMENT,
		tag     TEXT NOT NULL,
		run_at  TEXT NOT NULL,
		payload TEXT NOT NULL DEFAULT '{}'
	)
	""",
    "CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks (run_at)",
]

# Public alias for tooling (e.g. scripts/migrate_pg_to_sqlite.py) that needs
# the DDL without instantiating the class.
SCHEMA = _SCHEMA

# days per month, Feb counted at its leap maximum (29) so day=29 Feb-only
# specs are valid; month scans below are bounded past the widest gap
# between leap Februarys (8 years around century non-leap years)
_DAYS_IN_MONTH = {
    1: 31,
    2: 29,
    3: 31,
    4: 30,
    5: 31,
    6: 30,
    7: 31,
    8: 31,
    9: 30,
    10: 31,
    11: 30,
    12: 31,
}
_MONTH_SCAN = 100


def _as_tuple(value: int | tuple[int, ...]) -> tuple[int, ...]:
    """Normalize a single value or a tuple into a tuple."""
    return (value,) if isinstance(value, int) else value


def _chaotic_rng(jitter: float, seed: int | None) -> random.Random:
    """Validate ``jitter`` and build the seeded RNG (shared by the chaos pair)."""
    if not 0 <= jitter <= 1:
        raise ValueError(f"jitter must be between 0 and 1, got {jitter}")
    return random.Random(seed)


@dataclass(frozen=True, slots=True)
class At:
    """An absolute schedule: the task runs AT the declared calendar time.

    ``time`` is "HH:MM" (24h, UTC, zero-padded). Exactly one period
    selector applies:

    - ``weekday`` (0-6, Monday=0 … Sunday=6, or a non-empty tuple of
      them for several days a week): weekly on that/those weekday(s).
    - ``day`` (1-31, or -31…-1 counting from the end of the month, or a
      non-empty tuple of them): monthly on that/those day(s) of month —
      ``day=-1`` is the last day, Feb included; ``day=(15, -1)`` is the
      15th and the last day. ``months`` (1-12, ``None`` = every month)
      narrows it — the quarterly season rollover is ``day=1,
      months=(1, 4, 7, 10)``. A month lacking a day has no occurrence
      that period (cron skip semantics); specs with no possible
      occurrence at all are rejected at construction.
    - neither calendar selector: daily at ``time``.

    ``next_run`` is always strictly in the future; ``previous_run`` is
    the most recent occurrence at or before ``now``. ``missed`` is the
    catch-up rule: the last scheduled occurrence went unserviced (e.g.
    the bot was down at the scheduled moment) and should be forced now.
    """

    time: str = "00:00"
    weekday: int | tuple[int, ...] | None = None
    day: int | tuple[int, ...] | None = None
    months: tuple[int, ...] | None = None
    _hour: int = field(init=False, repr=False, compare=False)
    _minute: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate the schedule spec and cache the parsed hour/minute."""
        match = re.fullmatch(r"(\d{2}):(\d{2})", self.time)
        if match is None:
            raise ValueError(
                f"cadence time must be HH:MM (zero-padded), got {self.time!r}"
            )
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            raise ValueError(f"cadence time out of range: {self.time!r}")
        object.__setattr__(self, "_hour", hour)
        object.__setattr__(self, "_minute", minute)
        if self.weekday is not None:
            if isinstance(self.weekday, tuple) and not self.weekday:
                raise ValueError("cadence weekday must not be empty")
            for w in _as_tuple(self.weekday):
                if not 0 <= w <= 6:
                    raise ValueError(
                        f"cadence weekday must be 0-6, got {self.weekday}"
                    )
        if self.day is not None:
            if isinstance(self.day, tuple) and not self.day:
                raise ValueError("cadence day must not be empty")
            for d in _as_tuple(self.day):
                if not 1 <= abs(d) <= 31:
                    raise ValueError(
                        f"cadence day must be 1-31 or -31…-1, got {self.day}"
                    )
        if self.weekday is not None and self.day is not None:
            raise ValueError(
                "cadence takes either weekday or day, not both"
            )
        if self.months is not None:
            if not self.months:
                raise ValueError("cadence months must not be empty")
            if self.day is None:
                raise ValueError("cadence months require a day")
            for month in self.months:
                if not 1 <= month <= 12:
                    raise ValueError(
                        f"cadence month must be 1-12, got {month}"
                    )
            days = _as_tuple(self.day)
            if all(
                all(_DAYS_IN_MONTH[m] < abs(d) for d in days)
                for m in self.months
            ):
                raise ValueError(
                    "cadence never occurs: no eligible month has any declared day"
                )

    def _clock(self) -> tuple[int, int]:
        """The parsed ``(hour, minute)`` from ``time``."""
        return self._hour, self._minute

    def next_run(self, now: pendulum.DateTime) -> pendulum.DateTime:
        """The next occurrence of this cadence, strictly after ``now``."""
        if self.weekday is not None:
            return self._next_weekly(now, self.weekday)
        if self.day is not None:
            return self._next_monthly(now, self.day, self.months)
        return self._next_daily(now)

    def previous_run(self, now: pendulum.DateTime) -> pendulum.DateTime:
        """The most recent occurrence at or before ``now``."""
        if self.weekday is not None:
            return self._previous_weekly(now, self.weekday)
        if self.day is not None:
            return self._previous_monthly(now, self.day, self.months)
        return self._previous_daily(now)

    def missed(
        self, last_run: pendulum.DateTime, now: pendulum.DateTime
    ) -> bool:
        """True when the most recent scheduled occurrence went unserviced.

        The catch-up rule for boot forcing: if the last recorded run
        predates the last scheduled occurrence, a run was missed and
        should be forced now.
        """
        return last_run < self.previous_run(now)

    # -- daily -----------------------------------------------------------

    def _next_daily(self, now: pendulum.DateTime) -> pendulum.DateTime:
        """The next daily occurrence at ``time``, strictly after ``now``."""
        hour, minute = self._clock()
        candidate = now.start_of("day").replace(hour=hour, minute=minute)
        if candidate <= now:
            candidate = candidate.add(days=1)
        return candidate

    def _previous_daily(self, now: pendulum.DateTime) -> pendulum.DateTime:
        """The most recent daily occurrence at ``time``, at-or-before ``now``."""
        hour, minute = self._clock()
        candidate = now.start_of("day").replace(hour=hour, minute=minute)
        if candidate > now:
            candidate = candidate.subtract(days=1)
        return candidate

    # -- weekly ----------------------------------------------------------

    def _next_weekly(
        self, now: pendulum.DateTime, weekdays: int | tuple[int, ...]
    ) -> pendulum.DateTime:
        """The soonest upcoming occurrence across the weekday(s)."""
        hour, minute = self._clock()
        base = now.start_of("day")
        upcoming: list[pendulum.DateTime] = []
        for w in _as_tuple(weekdays):
            candidate = base.add(days=(w - now.weekday()) % 7).replace(
                hour=hour, minute=minute
            )
            if candidate <= now:
                candidate = candidate.add(days=7)
            upcoming.append(candidate)
        return min(upcoming)

    def _previous_weekly(
        self, now: pendulum.DateTime, weekdays: int | tuple[int, ...]
    ) -> pendulum.DateTime:
        """The most recent occurrence across the weekday(s), at-or-before now."""
        hour, minute = self._clock()
        base = now.start_of("day")
        past: list[pendulum.DateTime] = []
        for w in _as_tuple(weekdays):
            candidate = base.subtract(
                days=(now.weekday() - w) % 7
            ).replace(hour=hour, minute=minute)
            if candidate > now:
                candidate = candidate.subtract(days=7)
            past.append(candidate)
        return max(past)

    # -- monthly family --------------------------------------------------

    def _next_monthly(
        self,
        now: pendulum.DateTime,
        day: int | tuple[int, ...],
        months: tuple[int, ...] | None,
    ) -> pendulum.DateTime:
        """The soonest upcoming occurrence across the day(s), month by month.

        A month outside ``months`` or lacking every listed day simply has
        no occurrence that period. Validated specs always find one within
        the scan (the widest gap is a leap Feb 29, at most 8 years).
        """
        hour, minute = self._clock()
        month = now.start_of("month")
        for _ in range(_MONTH_SCAN):
            for candidate in self._month_occurrences(
                month, day, months, hour, minute
            ):
                if candidate > now:
                    return candidate
            month = month.add(months=1)
        raise ValueError(f"cadence {self} has no upcoming occurrence")

    def _previous_monthly(
        self,
        now: pendulum.DateTime,
        day: int | tuple[int, ...],
        months: tuple[int, ...] | None,
    ) -> pendulum.DateTime:
        """The most recent occurrence across the day(s), at-or-before now."""
        hour, minute = self._clock()
        month = now.start_of("month")
        for _ in range(_MONTH_SCAN):
            occurrences = self._month_occurrences(
                month, day, months, hour, minute
            )
            for candidate in reversed(occurrences):
                if candidate <= now:
                    return candidate
            month = month.subtract(months=1)
        raise ValueError(f"cadence {self} has no previous occurrence")

    def _month_occurrences(
        self,
        month: pendulum.DateTime,
        day: int | tuple[int, ...],
        months: tuple[int, ...] | None,
        hour: int,
        minute: int,
    ) -> list[pendulum.DateTime]:
        """The valid occurrences in ``month`` for the day(s), ascending.

        Negative days count from the end of the month (``-1`` is the last
        day); positions the month lacks are skipped (e.g. Feb 31, or
        -31 in April).
        """
        if months is not None and month.month not in months:
            return []
        occurrences: list[pendulum.DateTime] = []
        for d in _as_tuple(day):
            target = month.days_in_month + d + 1 if d < 0 else d
            try:
                occurrences.append(
                    month.replace(day=target, hour=hour, minute=minute)
                )
            except ValueError:
                continue
        return sorted(occurrences)


@dataclass(frozen=True, slots=True)
class AtChaotic(At):
    """The chaotic flavor of ``At`` — same declarations, rolled runs.

    Inherits the full absolute declaration (``time``/``weekday``/``day``/
    ``months``) and adds the random-scheduling declarations: ``jitter``
    (0..1) and ``seed`` (deterministic tests). ``next_run`` overrides the
    base: the run lands at the scheduled occurrence plus up to ``jitter``
    of the period, drifting forward within the window (never past the
    next occurrence). ``previous_run``/``missed`` are inherited — the
    calendar occurrence is the scheduled instant, and missed handling
    stays per-handler (row-based catch-up). ``bounds`` is the RNG-free
    window the next roll lands in.
    """

    jitter: float = 0.0
    seed: int | None = None
    _rng: random.Random = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Chain the base validation and build this instance's seeded RNG."""
        super().__post_init__()
        object.__setattr__(
            self, "_rng", _chaotic_rng(self.jitter, self.seed)
        )

    @override
    def next_run(self, now: pendulum.DateTime) -> pendulum.DateTime:
        """The next instant — the base occurrence, rolled chaotically."""
        base = super().next_run(now)
        if self.jitter == 0:
            return base
        return base.add(
            seconds=self._rng.random() * self.jitter * self._period(base)
        )

    def bounds(
        self, now: pendulum.DateTime
    ) -> tuple[pendulum.DateTime, pendulum.DateTime]:
        """The deterministic window the next roll lands in (no RNG)."""
        base = super().next_run(now)
        return (base, base.add(seconds=self.jitter * self._period(base)))

    def _period(self, at: pendulum.DateTime) -> float:
        """Seconds from one occurrence to the next (calendar mode)."""
        return (super().next_run(at) - at).total_seconds()


@dataclass(frozen=True, slots=True)
class In:
    """A relative schedule: the task runs IN the declared duration.

    ``interval`` is positive seconds, or a duration string like ``"2h"``
    / ``"90m"`` parsed via ``timeparse.parse_duration``. ``next_run`` is
    ``now + interval``, re-armed relative to each fire — the schedule
    slides with the actual completion instant, so ``previous_run`` is
    ``now - interval`` and ``missed`` is "the last run is older than the
    interval".
    """

    interval: int | str

    def __post_init__(self) -> None:
        """Reject intervals that are not positive."""
        if self._interval_seconds() <= 0:
            raise ValueError(
                f"interval must be positive, got {self.interval!r}"
            )

    def _interval_seconds(self) -> int:
        """The duration declaration as whole seconds."""
        interval = self.interval
        if isinstance(interval, str):
            try:
                seconds = parse_duration(interval).total_seconds()
            except InvalidTimeError as err:
                raise ValueError(
                    f"invalid cadence interval {interval!r}"
                ) from err
            return int(seconds)
        return interval

    def next_run(self, now: pendulum.DateTime) -> pendulum.DateTime:
        """The next instant: ``now + interval``."""
        return now.add(seconds=self._interval_seconds())

    def previous_run(self, now: pendulum.DateTime) -> pendulum.DateTime:
        """The most recent instant: ``now - interval``."""
        return now.subtract(seconds=self._interval_seconds())

    def missed(
        self, last_run: pendulum.DateTime, now: pendulum.DateTime
    ) -> bool:
        """True when the last run is older than the interval."""
        return last_run < self.previous_run(now)


@dataclass(frozen=True, slots=True)
class InChaotic(In):
    """The chaotic flavor of ``In`` — the same declaration, rolled runs.

    ``next_run`` rolls ``now + interval * (1 ± jitter)`` fresh every
    call, so late runs self-correct by rolling from the actual
    completion instant. ``seed`` makes rolls deterministic for tests;
    ``bounds`` is the RNG-free window the next roll lands in.
    """

    jitter: float = 0.0
    seed: int | None = None
    _rng: random.Random = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Chain the base validation and build this instance's seeded RNG."""
        super().__post_init__()
        object.__setattr__(
            self, "_rng", _chaotic_rng(self.jitter, self.seed)
        )

    @override
    def next_run(self, now: pendulum.DateTime) -> pendulum.DateTime:
        """The next instant: ``now + interval * (1 ± jitter)``."""
        offset = self._interval_seconds() * (
            1 + (self._rng.random() - 0.5) * 2 * self.jitter
        )
        return now.add(seconds=offset)

    def bounds(
        self, now: pendulum.DateTime
    ) -> tuple[pendulum.DateTime, pendulum.DateTime]:
        """The deterministic window the next roll lands in (no RNG)."""
        seconds = self._interval_seconds()
        spread = seconds * self.jitter
        return (
            now.add(seconds=seconds - spread),
            now.add(seconds=seconds + spread),
        )


@dataclass(frozen=True, slots=True)
class TaskPolicy:
    """Dispatch policy for one task tag: retry + missed-run handling.

    Applies only to tasks whose payload declares ``retry: True`` — the
    rest resolve on completion regardless of success. ``max_attempts``
    caps handler retries before the task row is dropped (``None`` retries
    forever, so expiries like mutes still fire eventually). ``backoff`` is
    the delay in seconds between attempts; the last value repeats.
    ``stale_after`` is the missed-run rule: a row that came due while the
    bot was down and is this old when a tick sees it is dropped instead
    of fired (``None`` fires it no matter how old).
    """

    max_attempts: int | None = None
    backoff: tuple[int, ...] = (30, 60, 300)
    stale_after: timedelta | None = None

    def delay_for(self, attempt: int) -> int:
        """Retry delay (seconds) for a 0-based failed-attempt count."""
        return self.backoff[min(attempt, len(self.backoff) - 1)]


class Cadence(Protocol):
    """Anything with a ``next_run`` — the schedule declarations above."""

    def next_run(self, now: pendulum.DateTime) -> pendulum.DateTime:
        """The next occurrence of this cadence, strictly after ``now``."""
        ...


class Scheduler:
    """Owns the task table and dispatches due tasks once per second."""

    def __init__(self, bot: "CazzuBot", *, concurrency: int = 10) -> None:
        """Bind ``bot`` and register the ready gate; ``concurrency`` caps handlers."""
        self.bot = bot
        self.handlers: dict[str, TaskHandler] = {}
        self.policies: dict[str, TaskPolicy] = {}
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._concurrency = concurrency
        self._sem: asyncio.Semaphore | None = None
        # dispatched task rows (id -> runner task); a tick never re-dispatches
        # a row that is still in flight, and stop() drains/cancels from here
        self._running: dict[int, asyncio.Task[Any]] = {}
        self.bot.subscribe(hikari.StartedEvent, self._on_started)

    schema = _SCHEMA

    async def start(self) -> None:
        """Start the once-per-second dispatch loop (idempotent)."""
        if self._task is not None:
            return
        self._stopping = False
        self._sem = asyncio.Semaphore(self._concurrency)
        self._task = asyncio.create_task(self._run(), name="scheduler")

    async def stop(self) -> None:
        """Stop after the current tick, then drain in-flight handler tasks.

        Cancelling a task while it awaits an aiosqlite call kills the
        connection's worker thread (its future is already cancelled, so
        ``set_result`` raises inside the thread and it dies), which wedges
        every later db call — including ``close()`` during shutdown. The
        loop exits via a flag between ticks; handler tasks get a short
        grace period and are only cancelled as a last resort.
        """
        if self._task is None:
            return
        self._stopping = True
        if not self._ready.is_set():
            # never ticked — the loop task is parked on _ready.wait(), which
            # is safe to cancel (no db op in flight)
            await self._cancel_task()
        else:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                # pathological: a tick hung; cancel as a last resort
                await self._cancel_task()
        self._task = None
        self._stopping = False
        # no new dispatches now — wait for in-flight handlers, then cancel
        # whatever is still stuck (same aiosqlite caveat as above)
        if self._running:
            try:
                await asyncio.wait_for(self._drain(), timeout=5)
            except asyncio.TimeoutError:
                for runner in list(self._running.values()):
                    runner.cancel()
                await asyncio.gather(
                    *self._running.values(), return_exceptions=True
                )

    async def _cancel_task(self) -> None:
        """Cancel the loop task and await its end.

        Only safe when no db op is in flight (see ``stop``).
        """
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _on_started(self, _event: hikari.StartedEvent) -> None:
        """Tick only after the gateway is up (tasks may hit Discord APIs)."""
        self._ready.set()

    async def _run(self) -> None:
        """Wait for the ready gate, then tick once per second until stopped."""
        await self._ready.wait()
        while not self._stopping:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception("scheduler tick failed")
            await asyncio.sleep(1.0)

    def register(
        self,
        tag: str,
        handler: "TaskHandler",
        policy: TaskPolicy | None = None,
    ) -> None:
        """Register a handler for ``tag``, optionally with a policy."""
        self.handlers[tag] = handler
        if policy is not None:
            self.policies[tag] = policy
        _log.info("scheduler handler registered for tag %r", tag)

    # -- task rows --------------------------------------------------------

    async def add(
        self,
        tag: str,
        run_at: pendulum.DateTime,
        payload: dict[str, Any] | None = None,
    ) -> int | None:
        """Insert a task; returns its row id."""
        return await self.bot.db.execute_lastrowid(
            """
			INSERT INTO tasks (tag, run_at, payload)
			VALUES (?, ?, ?)
			""",
            tag,
            run_at.isoformat(),
            json.dumps(payload or {}),
        )

    async def get(
        self, tag: str, payload: dict[str, Any] | None = None
    ) -> list[Task]:
        """Fetch task rows; payload filters as a JSON-superset match."""
        rows = await self.bot.db.fetchall(
            "SELECT * FROM tasks WHERE tag = ?", tag
        )
        payload = payload or {}
        out: list[Task] = []
        for row in rows:
            task = Task.from_row(row)
            if all(task.payload.get(k) == v for k, v in payload.items()):
                out.append(task)
        return out

    async def drop(self, task_id: int) -> None:
        """Delete the task row with ``task_id``."""
        await self.bot.db.execute(
            "DELETE FROM tasks WHERE id = ?", task_id
        )

    async def drop_tag(self, tag: str) -> None:
        """Delete every task row with ``tag``."""
        await self.bot.db.execute("DELETE FROM tasks WHERE tag = ?", tag)

    async def update_run_at(
        self, task_id: int, run_at: pendulum.DateTime
    ) -> None:
        """Move the task row with ``task_id`` to a new ``run_at`` time."""
        await self.bot.db.execute(
            "UPDATE tasks SET run_at = ? WHERE id = ?",
            run_at.isoformat(),
            task_id,
        )

    async def arm(self, tag: str, cadence: Cadence) -> None:
        """Drop ``tag``'s stale rows and schedule its next occurrence.

        The cadence re-arm contract: the fired row is replaced by the
        next occurrence, retry-enabled (``retry: True``) so a failed
        handler bumps the row instead of silently dropping the schedule.
        """
        await self.drop_tag(tag)
        await self.add(
            tag, cadence.next_run(pendulum.now("UTC")), {"retry": True}
        )

    async def arm_if_rowless(self, tag: str, cadence: Cadence) -> None:
        """Like :meth:`arm`, but never clobbers an existing row.

        A row left from a previous run is either future (already armed)
        or overdue (the bot was down over the boundary — the scheduler
        fires it on boot and the work runs then). Only a rowless install
        needs a fresh arm.
        """
        if not await self.get(tag):
            await self.arm(tag, cadence)

    # -- loop -------------------------------------------------------------

    async def _tick(self) -> None:
        """Dispatch every due row — never awaits handlers (see _run_task)."""
        if not self.handlers:
            return
        now = pendulum.now("UTC")
        rows = await self.bot.db.fetchall(
            "SELECT * FROM tasks WHERE run_at <= ?", now.isoformat()
        )
        for row in rows:
            task = Task.from_row(row)
            if task.id in self._running:
                continue  # already dispatched; the done callback clears it
            handler = self.handlers.get(task.tag)
            if handler is None:
                _log.warning(
                    "no handler for task tag %r (dropped)",
                    task.tag,
                )
                await self.bot.db.execute(
                    "DELETE FROM tasks WHERE id = ?", task.id
                )
                continue

            policy = self.policies.get(task.tag, TaskPolicy())
            if _is_stale(task, now, policy.stale_after):
                _log.warning(
                    "dropping stale task %s (%r): due %s, missed by %s",
                    task.id,
                    task.tag,
                    task.run_at,
                    policy.stale_after,
                )
                await self.bot.db.execute(
                    "DELETE FROM tasks WHERE id = ?", task.id
                )
                continue

            runner = asyncio.create_task(
                self._run_task(handler, task, policy),
                name=f"sched-{task.tag}-{task.id}",
            )
            self._running[task.id] = runner
            # default arg binds the id per row (a bare closure over `task`
            # would capture the loop variable and pop the wrong id)
            runner.add_done_callback(
                lambda _fut, tid=task.id: self._running.pop(tid, None)
            )

    async def _run_task(
        self,
        handler: "TaskHandler",
        task: Task,
        policy: TaskPolicy,
    ) -> None:
        """Run one dispatched task: the row resolves when the handler ends.

        By default a task resolves regardless of success (the fired row is
        deleted — v1's contract). A task whose payload declares
        ``retry: True`` opts into guaranteed handling: on exception the
        row is kept and re-armed per the tag's ``TaskPolicy`` (backoff,
        attempt cap) until it succeeds or the cap is hit. Arm-last
        handlers pair with retry (the fired row must stay live through
        the work); fire-and-forget handlers pair with schedule-first.
        """
        assert self._sem is not None  # start() precedes any dispatch
        async with self._sem:
            try:
                await handler(self.bot, task.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                if not task.payload.get("retry"):
                    # fire-and-forget: the task resolves anyway, like v1
                    _log.exception(
                        "task %s (%r) handler failed; resolving anyway",
                        task.id,
                        task.tag,
                    )
                    await self.bot.db.execute(
                        "DELETE FROM tasks WHERE id = ?", task.id
                    )
                    return
                _log.exception(
                    "task %s (%r) handler failed; retrying",
                    task.id,
                    task.tag,
                )
                await self._schedule_retry(task, policy)
                return
            await self.bot.db.execute(
                "DELETE FROM tasks WHERE id = ?", task.id
            )

    async def _schedule_retry(
        self, task: Task, policy: TaskPolicy
    ) -> None:
        """Apply the retry policy after a handler failure.

        Bumps ``payload["attempt"]`` (persisted, so the count survives
        restarts), pushes ``run_at`` forward by the policy's backoff, or
        drops the row once ``max_attempts`` is exceeded.
        """
        attempt = int(task.payload.get("attempt", 0)) + 1
        if (
            policy.max_attempts is not None
            and attempt > policy.max_attempts
        ):
            _log.error(
                "task %s (%r) failed %d times; dropping",
                task.id,
                task.tag,
                attempt,
            )
            await self.bot.db.execute(
                "DELETE FROM tasks WHERE id = ?", task.id
            )
            return
        delay = policy.delay_for(attempt - 1)
        payload = dict(task.payload)
        payload["attempt"] = attempt
        await self.bot.db.execute(
            """
			UPDATE tasks SET run_at = ?, payload = ?
			WHERE id = ?
			""",
            _now(delay),
            json.dumps(payload),
            task.id,
        )
        _log.info(
            "task %s (%r) retrying in %ds (attempt %d)",
            task.id,
            task.tag,
            delay,
            attempt,
        )

    async def _drain(self) -> None:
        """Wait until every dispatched handler task has finished."""
        while self._running:
            await asyncio.sleep(0.01)


@dataclass(slots=True)
class Task:
    """One ``tasks`` row with the JSON ``payload`` already parsed."""

    id: int
    tag: str
    run_at: str
    payload: dict[str, Any]

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> Task:
        """Parse a raw task row (payload column is JSON text)."""
        return cls(
            id=row["id"],
            tag=row["tag"],
            run_at=row["run_at"],
            payload=json.loads(row["payload"]),
        )


def _is_stale(
    task: Task,
    now: pendulum.DateTime,
    stale_after: timedelta | None,
) -> bool:
    """True when a due task was scheduled too long ago to still run.

    The missed-run rule: rows that came due while the bot was down and
    waited longer than ``stale_after`` are dropped instead of fired
    (``None`` = fire no matter how old — the default).
    """
    if stale_after is None:
        return False
    scheduled = pendulum.parse(task.run_at)
    if not isinstance(scheduled, pendulum.DateTime):
        # unparseable timestamp — run it rather than drop it
        return False
    return (now - scheduled).total_seconds() > stale_after.total_seconds()


def _now(offset_seconds: int = 0) -> str:
    """ISO-8601 UTC timestamp, optionally ``offset_seconds`` ahead."""
    return pendulum.now("UTC").add(seconds=offset_seconds).isoformat()
