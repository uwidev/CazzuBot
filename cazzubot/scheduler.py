"""Central scheduler for DB-backed delayed tasks.

One loop polls the ``tasks`` table every second and dispatches due rows to the
handler registered for their tag. Handlers re-schedule by inserting new rows,
so tasks survive restarts (mute expiry, frog spawns, counter expiry, …).

Replaces v1's per-cog ``@tasks.loop(seconds=1)`` polling of the same table.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
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


class Scheduler:
    """Owns the task table and runs due tasks once per second."""

    def __init__(self, bot: "CazzuBot") -> None:
        self.bot = bot
        self.handlers: dict[str, TaskHandler] = {}
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self.bot.subscribe(hikari.StartedEvent, self._on_started)

    @property
    def schema(self) -> list[str]:
        return _SCHEMA

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="scheduler")

    async def stop(self) -> None:
        """Stop after the current tick, never mid-aiosqlite-op.

        Cancelling the task while it awaits an aiosqlite call kills the
        connection's worker thread (its future is already cancelled, so
        ``set_result`` raises inside the thread and it dies), which wedges
        every later db call — including ``close()`` during shutdown. A flag
        lets the loop exit between ticks instead.
        """
        if self._task is None:
            return
        self._stopping = True
        if not self._ready.is_set():
            # never ticked — the task is parked on _ready.wait(), which is
            # safe to cancel (no db op in flight)
            await self._cancel_task()
        else:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                # pathological: a tick handler hung; cancel as a last resort
                await self._cancel_task()
        self._task = None
        self._stopping = False

    async def _cancel_task(self) -> None:
        """Cancel the loop task and await its end.

        Only safe when no db op is in flight (see ``stop``).
        """
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

    def register(self, tag: str, handler: "TaskHandler") -> None:
        self.handlers[tag] = handler
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

    # -- loop -------------------------------------------------------------

    async def _tick(self) -> None:
        if not self.handlers:
            return
        now = _now()
        rows = await self.bot.db.fetchall(
            "SELECT * FROM tasks WHERE run_at <= ?", now
        )
        for row in rows:
            task = Task.from_row(row)
            payload = task.payload
            tag = task.tag
            task_id = task.id
            handler = self.handlers.get(tag)
            if handler is None:
                _log.warning(
                    "no handler for task tag %r (dropped)",
                    tag,
                )
                await self.bot.db.execute(
                    "DELETE FROM tasks WHERE id = ?", task_id
                )
                continue

            try:
                await handler(self.bot, payload)
            except Exception:
                # keep the task so transient failures don't drop it (e.g. a
                # mute that never expires); retry shortly after.
                _log.exception(
                    "task %s (%r) handler failed; retrying in 30s",
                    task_id,
                    tag,
                )
                await self.bot.db.execute(
                    """
					UPDATE tasks SET run_at = ?
					WHERE id = ?
					""",
                    _now(30),
                    task_id,
                )
                continue

            await self.bot.db.execute(
                "DELETE FROM tasks WHERE id = ?", task_id
            )


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


def _now(offset_seconds: int = 0) -> str:
    return pendulum.now("UTC").add(seconds=offset_seconds).isoformat()
