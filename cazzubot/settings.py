"""Generic key-value settings store (single guild).

Replaces v1's ``db/guild.py``, ``db/internal.py`` and most per-feature
settings getters. Values are JSON-serialized; timestamps stored ISO-8601.

Plugins should namespace their keys, e.g. ``"mod.mute_role"``.
"""

import logging
from typing import Any

from cazzubot.db import Database, dump_json, load_json

_log = logging.getLogger(__name__)

_SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS settings (
		key   TEXT PRIMARY KEY,
		value TEXT NOT NULL
	)
	""",
]

# Public alias for tooling (e.g. scripts/migrate_pg_to_sqlite.py) that needs
# the DDL without instantiating the class.
SCHEMA = _SCHEMA


class Settings:
    """Key-value access layered on the ``settings`` table."""

    schema = _SCHEMA

    def __init__(self, db: Database) -> None:
        """Bind the key-value store to ``db``."""
        self.db = db

    async def get(self, key: str, default: Any = None) -> Any:
        """The JSON value for ``key``, or ``default`` when unset."""
        row = await self.db.fetchone(
            "SELECT value FROM settings WHERE key = ?", key
        )
        return load_json(row["value"], default) if row else default

    async def set(self, key: str, value: Any) -> None:
        """Persist ``key`` -> JSON-serialized ``value`` (upsert)."""
        await self.db.execute(
            """
			INSERT INTO settings (key, value) VALUES (?, ?)
			ON CONFLICT (key) DO UPDATE SET value = excluded.value
			""",
            key,
            dump_json(value),
        )

    async def delete(self, key: str) -> None:
        """Remove ``key``."""
        await self.db.execute("DELETE FROM settings WHERE key = ?", key)

    async def all(self) -> dict[str, Any]:
        """Every key-value pair as a dict."""
        rows = await self.db.fetchall("SELECT key, value FROM settings")
        return {r["key"]: load_json(r["value"]) for r in rows}
