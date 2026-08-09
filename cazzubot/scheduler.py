"""Central scheduler for DB-backed delayed tasks.

One loop polls the ``tasks`` table every second and dispatches due rows to
the handler registered for their tag. Handlers re-schedule by inserting new
rows, so tasks survive restarts (mute expiry, frog spawns, counter expiry, …).

Dispatch is concurrent: each due row runs in its own asyncio task (bounded
by a semaphore), so a slow handler never stalls the loop or other tasks.
Per-tag ``TaskPolicy`` controls retry behavior (backoff, attempt cap) and the
missed-run rule for rows that came due while the bot was down.

Replaces v1's per-cog ``@tasks.loop(seconds=1)`` polling of the same table.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiosqlite
import hikari
import pendulum

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


@dataclass(frozen=True, slots=True)
class Cadence:
    """A repeating schedule: daily at ``time``, or weekly on ``weekday``.

    ``time`` is "HH:MM" (24h, UTC, zero-padded); ``weekday`` is ``None``
    for daily or 0-6 (Monday=0 … Sunday=6) for weekly. ``next_run`` is
    always strictly in the future; ``previous_run`` is the most recent
    occurrence at or before ``now``. ``missed`` is the catch-up rule: the
    last scheduled occurrence went unserviced (e.g. the bot was down at
    the scheduled moment) and should be forced now.
    """

    time: str
    weekday: int | None = None

    def __post_init__(self) -> None:
        match = re.fullmatch(r"(\d{2}):(\d{2})", self.time)
        if match is None:
            raise ValueError(
                f"cadence time must be HH:MM (zero-padded), got {self.time!r}"
            )
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            raise ValueError(f"cadence time out of range: {self.time!r}")
        if self.weekday is not None and not 0 <= self.weekday <= 6:
            raise ValueError(
                f"cadence weekday must be 0-6 (Monday=0), got {self.weekday}"
            )

    def _clock(self) -> tuple[int, int]:
        match = re.fullmatch(r"(\d{2}):(\d{2})", self.time)
        assert match is not None  # validated in __post_init__
        return int(match.group(1)), int(match.group(2))

    def next_run(self, now: pendulum.DateTime) -> pendulum.DateTime:
        """The next occurrence of this cadence, strictly after ``now``."""
        hour, minute = self._clock()
        candidate = now.start_of("day").replace(hour=hour, minute=minute)
        if self.weekday is not None:
            days_ahead = (self.weekday - now.weekday()) % 7
            candidate = candidate.add(days=days_ahead)
            if days_ahead == 0 and candidate <= now:
                candidate = candidate.add(days=7)
        elif candidate <= now:
            candidate = candidate.add(days=1)
        return candidate

    def previous_run(self, now: pendulum.DateTime) -> pendulum.DateTime:
        """The most recent occurrence at or before ``now``."""
        hour, minute = self._clock()
        candidate = now.start_of("day").replace(hour=hour, minute=minute)
        if self.weekday is not None:
            days_back = (now.weekday() - self.weekday) % 7
            candidate = candidate.subtract(days=days_back)
            if candidate > now:
                candidate = candidate.subtract(days=7)
        elif candidate > now:
            candidate = candidate.subtract(days=1)
        return candidate

    def missed(
        self, last_run: pendulum.DateTime, now: pendulum.DateTime
    ) -> bool:
        """True when the most recent scheduled occurrence went unserviced.

        The catch-up rule for boot forcing: if the last recorded run
        predates the last scheduled occurrence, a run was missed and
        should be forced now.
        """
        return last_run < self.previous_run(now)


@dataclass(frozen=True, slots=True)
class TaskPolicy:
    """Dispatch policy for one task tag: retry + missed-run handling.

    ``max_attempts`` caps handler retries before the task row is dropped;
    ``None`` retries forever (the default, so expiries like mutes still
    fire eventually). ``backoff`` is the delay in seconds between attempts;
    the last value repeats. ``stale_after`` is the missed-run rule: a row
    that came due while the bot was down and is this old when a tick sees
    it is dropped instead of fired (``None`` fires it no matter how old).
    """

    max_attempts: int | None = None
    backoff: tuple[int, ...] = (30, 60, 300)
    stale_after: timedelta | None = None

    def delay_for(self, attempt: int) -> int:
        """Retry delay (seconds) for a 0-based failed-attempt count."""
        return self.backoff[min(attempt, len(self.backoff) - 1)]


class Scheduler:
    """Owns the task table and dispatches due tasks once per second."""

    def __init__(
        self, bot: "CazzuBot", *, concurrency: int = 10
    ) -> None:
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

    @property
    def schema(self) -> list[str]:
        return _SCHEMA

    async def start(self) -> None:
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
        await self.bot.db.execute(
            "DELETE FROM tasks WHERE id = ?", task_id
        )

    async def drop_tag(self, tag: str) -> None:
        await self.bot.db.execute("DELETE FROM tasks WHERE tag = ?", tag)

    async def update_run_at(
        self, task_id: int, run_at: pendulum.DateTime
    ) -> None:
        await self.bot.db.execute(
            "UPDATE tasks SET run_at = ? WHERE id = ?",
            run_at.isoformat(),
            task_id,
        )

    async def arm(self, tag: str, cadence: Cadence) -> None:
        """Re-arm a cadence tag: drop stale rows, schedule the next run.

        The generalized ``arm_midnight_cadence`` — any daily/weekly
        cadence, not just midnight. Handlers call this to re-schedule
        themselves; plugins force missed runs on boot via
        ``Cadence.missed``.
        """
        await self.drop_tag(tag)
        await self.add(tag, cadence.next_run(pendulum.now("UTC")), {})

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
        """Run one dispatched task: success deletes the row, failure retries.

        Executes as its own asyncio task under the concurrency semaphore,
        so a slow handler never blocks the tick loop or other tags.
        Failure applies the tag's ``TaskPolicy`` (backoff + attempt cap);
        success deletes the row exactly as before.
        """
        assert self._sem is not None  # start() precedes any dispatch
        async with self._sem:
            try:
                await handler(self.bot, task.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception(
                    "task %s (%r) handler failed", task.id, task.tag
                )
                await self._schedule_retry(task, policy)
                return
            await self.bot.db.execute(
                "DELETE FROM tasks WHERE id = ?", task.id
            )

    async def _schedule_retry(self, task: Task, policy: TaskPolicy) -> None:
        """Apply the retry policy after a handler failure.

        Bumps ``payload["attempt"]`` (persisted, so the count survives
        restarts), pushes ``run_at`` forward by the policy's backoff, or
        drops the row once ``max_attempts`` is exceeded.
        """
        attempt = int(task.payload.get("attempt", 0)) + 1
        if policy.max_attempts is not None and attempt > policy.max_attempts:
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
    return (
        now - scheduled
    ).total_seconds() > stale_after.total_seconds()


def _now(offset_seconds: int = 0) -> str:
    return pendulum.now("UTC").add(seconds=offset_seconds).isoformat()
