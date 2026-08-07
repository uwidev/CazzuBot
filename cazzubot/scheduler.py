"""Central scheduler for DB-backed delayed tasks.

One loop polls the ``tasks`` table every second and dispatches due rows to the
handler registered for their tag. Handlers re-schedule by inserting new rows,
so tasks survive restarts (mute expiry, frog spawns, counter expiry, …).

Replaces v1's per-cog ``@tasks.loop(seconds=1)`` polling of the same table.
"""

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiosqlite
import pendulum
from discord.ext import tasks

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
        self._loop = tasks.loop(seconds=1.0)(self._tick)

    @property
    def schema(self) -> list[str]:
        return _SCHEMA

    async def start(self) -> None:
        self._loop.before_loop(self._before_loop)
        self._loop.start()

    async def stop(self) -> None:
        if self._loop.is_running():
            self._loop.cancel()

    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

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
                    pendulum.now("UTC").add(seconds=30).isoformat(),
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


def _now() -> str:
    return pendulum.now("UTC").isoformat()
