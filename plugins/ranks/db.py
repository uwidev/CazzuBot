"""Ranks plugin — ranked roles based on level thresholds.

Single-guild port of v1's ``ext/rank.py`` + ``src/rank.py`` +
``src/db/rank_threshold.py`` + ``src/db/rank.py``. Settings live in the
generic settings store under ``rank.{mode}.`` keys.
"""

from dataclasses import dataclass

import pendulum

from typing import Any

from cazzubot.db import Database
from cazzubot.models import WindowEnum
from cazzubot.settings import Settings
from cazzubot.utils import month2season

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS rank_threshold (
		rid       INTEGER NOT NULL,
		threshold INTEGER NOT NULL,
		mode      TEXT NOT NULL DEFAULT 'seasonal',
		PRIMARY KEY (rid, mode)
	)
	""",
]


@dataclass(slots=True)
class RankThreshold:
    """One ``rank_threshold`` row for a window."""

    rid: int
    threshold: int
    mode: str


# -- rank_threshold table --------------------------------------------------


async def add(
    db: Database,
    rid: int,
    threshold: int,
    *,
    mode: WindowEnum = WindowEnum.SEASONAL,
) -> None:
    await db.execute(
        """
		INSERT OR REPLACE INTO rank_threshold (rid, threshold, mode)
		VALUES (?, ?, ?)
		""",
        rid,
        threshold,
        mode.value,
    )


async def get(
    db: Database, *, mode: WindowEnum = WindowEnum.SEASONAL
) -> list[RankThreshold]:
    return await db.fetch_models(
        RankThreshold,
        """
		SELECT rid, threshold, mode
		FROM rank_threshold
		WHERE mode = ?
		ORDER BY threshold
		""",
        mode.value,
    )


async def delete(db: Database, rid: int, mode: WindowEnum) -> None:
    """Delete the threshold row for a role id."""
    await db.execute(
        "DELETE FROM rank_threshold WHERE mode = ? AND rid = ?",
        mode.value,
        rid,
    )


async def batch_delete(db: Database, rids: list[int]) -> None:
    if not rids:
        return
    placeholders = ",".join("?" * len(rids))
    await db.execute(
        f"DELETE FROM rank_threshold WHERE rid IN ({placeholders})",
        *rids,
    )


async def drop(db: Database, mode: WindowEnum) -> None:
    await db.execute(
        "DELETE FROM rank_threshold WHERE mode = ?", mode.value
    )


async def of_member(
    db: Database,
    uid: int,
    *,
    mode: WindowEnum = WindowEnum.SEASONAL,
) -> int | None:
    """The rank role id a member currently holds (None if below all)."""
    thresholds = await get(db, mode=mode)
    if not thresholds:
        return None

    now = pendulum.now("UTC")
    if mode is WindowEnum.SEASONAL:
        from plugins.experience.db import seasonal_exp

        level = await seasonal_exp(
            db, uid, now.year, month2season(now.month)
        )
    else:
        from plugins.experience.db import get_member_exp

        member = await get_member_exp(db, uid)
        level = member.lifetime if member is not None else 0

    return calc_min_rank(thresholds, level)[0]


def calc_min_rank(
    thresholds: list[RankThreshold], level: int
) -> tuple[int | None, int | None]:
    """Naive scan: (rid, index) of the highest threshold <= level."""
    if not thresholds or level < thresholds[0].threshold:
        return None, None
    for i in range(1, len(thresholds)):
        if level < thresholds[i].threshold:
            return thresholds[i - 1].rid, i - 1
    return thresholds[-1].rid, len(thresholds) - 1


# -- settings --------------------------------------------------------------


async def get_message(
    settings: Settings, mode: WindowEnum = WindowEnum.SEASONAL
) -> dict[str, Any] | None:
    return await settings.get(_key(mode, "message"))


async def set_message(
    settings: Settings,
    message: dict[str, Any],
    mode: WindowEnum = WindowEnum.SEASONAL,
) -> None:
    await settings.set(_key(mode, "message"), message)


async def get_enabled(
    settings: Settings, mode: WindowEnum = WindowEnum.SEASONAL
) -> bool:
    return bool(await settings.get(_key(mode, "enabled"), False))


async def set_enabled(
    settings: Settings,
    val: bool,
    mode: WindowEnum = WindowEnum.SEASONAL,
) -> None:
    await settings.set(_key(mode, "enabled"), val)


async def get_keep_old(
    settings: Settings, mode: WindowEnum = WindowEnum.SEASONAL
) -> bool:
    return bool(await settings.get(_key(mode, "keep_old"), True))


async def set_keep_old(
    settings: Settings,
    val: bool,
    mode: WindowEnum = WindowEnum.SEASONAL,
) -> None:
    await settings.set(_key(mode, "keep_old"), val)


def _key(mode: WindowEnum, field: str) -> str:
    return f"rank.{mode.value}.{field}"
