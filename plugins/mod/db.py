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
) -> None:
    await db.execute(
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


async def get_mute_role(settings: Settings) -> int | None:
    return await settings.get(MUTE_ROLE_KEY)


async def set_mute_role(settings: Settings, rid: int) -> None:
    await settings.set(MUTE_ROLE_KEY, rid)
