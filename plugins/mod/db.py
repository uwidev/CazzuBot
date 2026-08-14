"""Mod plugin — repository layer: modlog entries and mute-role setting.

Single-guild port of v1's ``src/db/modlog.py``.
"""

import pendulum

from cazzubot.db import Database
from cazzubot.models import ModlogStatusEnum, ModlogTypeEnum
from cazzubot.settings import Settings

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS modlog (
		id         INTEGER PRIMARY KEY AUTOINCREMENT,
		uid        INTEGER NOT NULL,
		log_type   TEXT NOT NULL,
		given_on   TEXT NOT NULL,
		status     TEXT NOT NULL DEFAULT 'active',
		expires_on TEXT,
		reason     TEXT
	)
	""",
]

MUTE_ROLE_KEY = "mod.mute_role"


async def add_log(
    db: Database,
    uid: int,
    log_type: ModlogTypeEnum,
    given_on: pendulum.DateTime,
    *,
    expires_on: pendulum.DateTime | None = None,
    reason: str | None = None,
) -> int:
    """Record a modlog entry; returns its row id (the task payload
    references it so an expiry can mark exactly this row resolved)."""
    row_id = await db.execute_lastrowid(
        """
		INSERT INTO modlog (uid, log_type, given_on, status, expires_on, reason)
		VALUES (?, ?, ?, ?, ?, ?)
		""",
        uid,
        log_type.value,
        given_on.isoformat(),
        ModlogStatusEnum.ACTIVE.value,
        expires_on.isoformat() if expires_on else None,
        reason,
    )
    assert row_id is not None  # an INSERT always assigns a rowid
    return row_id


async def pending_expiries(
    db: Database,
) -> list[tuple[int, int, str, pendulum.DateTime]]:
    """Active modlog rows with a deadline: [(log_id, uid, log_type, expires_on)].

    The **source of truth** for state-backed scheduling: scheduler rows
    are projections of this list, rebuilt on load and withdrawn on unload.
    """
    rows = await db.fetchall(
        """
		SELECT id, uid, log_type, expires_on FROM modlog
		WHERE status = ? AND expires_on IS NOT NULL
		""",
        ModlogStatusEnum.ACTIVE.value,
    )
    out: list[tuple[int, int, str, pendulum.DateTime]] = []
    for row in rows:
        expires_on = pendulum.parse(row["expires_on"])
        if isinstance(expires_on, pendulum.DateTime):
            out.append(
                (row["id"], row["uid"], row["log_type"], expires_on)
            )
    return out


async def mark_resolved(db: Database, log_id: int) -> None:
    """Mark a modlog row resolved (an expiry just reverted it)."""
    await db.execute(
        "UPDATE modlog SET status = ? WHERE id = ? AND status = ?",
        ModlogStatusEnum.PARDONED.value,
        log_id,
        ModlogStatusEnum.ACTIVE.value,
    )


async def mark_resolved_for(db: Database, uid: int, log_type: str) -> None:
    """Resolve every active row of a user + type (fallback for rows whose
    task payload predates log_id)."""
    await db.execute(
        "UPDATE modlog SET status = ? WHERE uid = ? AND log_type = ? AND status = ?",
        ModlogStatusEnum.PARDONED.value,
        uid,
        log_type,
        ModlogStatusEnum.ACTIVE.value,
    )


async def get_mute_role(settings: Settings) -> int | None:
    return await settings.get(MUTE_ROLE_KEY)


async def set_mute_role(settings: Settings, rid: int) -> None:
    await settings.set(MUTE_ROLE_KEY, rid)
