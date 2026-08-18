"""Member effects — per-member modifiers the app pulls for calculations.

"All effects on a member": timed or permanent modifiers (e.g. a ×2 message
exp multiplier) keyed by a typed :class:`MemberEffectKey`, with a numeric
value and an optional expiry. Internal calculations read them at use time
(``experience.logic.award_exp`` applies the exp multiplier); expiry is
**lazy** — a past ``expires_at`` reads as absent and prunes the row, so
nothing needs a sweeper task.

Call graph (per the self-documenting rule): writers call :func:`set`
(e.g. a future ``exp_multiplier`` catch effect); readers call :func:`get`
(``award_exp``, the current consumer); :func:`clear` removes a modifier
explicitly. Tests drive all three directly.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

import pendulum

from cazzubot.db import Database

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)

_SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS member_effect (
		uid        INTEGER NOT NULL,
		key        TEXT NOT NULL,
		value      REAL NOT NULL,
		expires_at TEXT,
		PRIMARY KEY (uid, key)
	)
	""",
]

# Public alias for tooling that needs the DDL without instantiating the class.
SCHEMA = _SCHEMA


class MemberEffectKey(Enum):
    """The known member modifiers — typed keys, never bare strings."""

    EXP_MULTIPLIER = "exp_multiplier"


async def set(
    db: Database,
    uid: int,
    key: MemberEffectKey,
    value: float,
    *,
    expires_at: pendulum.DateTime | None = None,
) -> None:
    """Set a modifier; ``expires_at=None`` makes it permanent."""
    await db.execute(
        """
		INSERT INTO member_effect (uid, key, value, expires_at)
		VALUES (?, ?, ?, ?)
		ON CONFLICT (uid, key) DO UPDATE SET
			value = excluded.value,
			expires_at = excluded.expires_at
		""",
        uid,
        key.value,
        value,
        expires_at.isoformat() if expires_at is not None else None,
    )


async def get(
    db: Database,
    uid: int,
    key: MemberEffectKey,
    *,
    now: pendulum.DateTime | None = None,
) -> float | None:
    """The modifier value, or None when absent or expired.

    Lazy expiry: a past ``expires_at`` reads as absent and the row is
    pruned (read-time cleanup, no sweeper). ``now`` is injected for tests.
    """
    row = await db.fetchone(
        "SELECT value, expires_at FROM member_effect WHERE uid = ? AND key = ?",
        uid,
        key.value,
    )
    if row is None:
        return None
    if row["expires_at"] is not None:
        expires_at = pendulum.parse(row["expires_at"])
        if not isinstance(expires_at, pendulum.DateTime):
            return row["value"]
        if expires_at <= (now or pendulum.now("UTC")):
            await db.execute(
                "DELETE FROM member_effect WHERE uid = ? AND key = ?",
                uid,
                key.value,
            )
            return None
    return row["value"]


async def clear(db: Database, uid: int, key: MemberEffectKey) -> None:
    """Remove a modifier explicitly."""
    await db.execute(
        "DELETE FROM member_effect WHERE uid = ? AND key = ?",
        uid,
        key.value,
    )


class MemberEffects:
    """The member-effects service on the bot (``bot.member_effects``).

    Owns the schema (run at boot like settings/scheduler/assets) and
    delegates the same operations against ``bot.db`` for consumers that
    hold the bot rather than a Database.
    """

    schema = _SCHEMA

    def __init__(self, bot: "CazzuBot") -> None:
        """Bind the service to ``bot``."""
        self.bot = bot

    async def set(
        self,
        uid: int,
        key: MemberEffectKey,
        value: float,
        *,
        expires_at: pendulum.DateTime | None = None,
    ) -> None:
        """Set a modifier (``expires_at=None`` makes it permanent)."""
        return await set(
            self.bot.db, uid, key, value, expires_at=expires_at
        )

    async def get(
        self,
        uid: int,
        key: MemberEffectKey,
        *,
        now: pendulum.DateTime | None = None,
    ) -> float | None:
        """A member's modifier value, or None when absent or expired."""
        return await get(self.bot.db, uid, key, now=now)

    async def clear(self, uid: int, key: MemberEffectKey) -> None:
        """Remove a modifier explicitly."""
        return await clear(self.bot.db, uid, key)
