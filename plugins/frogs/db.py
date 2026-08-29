"""Frogs plugin — species token economy. DB queries.

Single-guild port of v1's ``ext/frog.py`` + ``src/frog_factory.py`` +
``src/db/member_frog.py`` + ``src/db/member_frog_log.py`` + ``src/db/frog.py``
+ ``src/db/frog_spawn.py``, reworked for the species model: holdings live in
the **generic inventory** (``cazzubot/inventory.py`` — frog stacks are
``FrogItem`` identities over it), ``member_frog`` only the lifetime capture
counter, and ``member_frog_log.type`` stores the species key. The species
*definitions* themselves live in code (``species.py`` — no catalog table).
"""

from dataclasses import dataclass
from typing import Any

import pendulum

from cazzubot import inventory
from cazzubot.db import Database
from cazzubot.models import FrogState, FrogItemKey
from cazzubot.settings import Settings
from cazzubot.utils import rank_rows, season_bounds

from .effects import frog_item_key
from .species import SPECIES

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS member_frog (
		uid     INTEGER PRIMARY KEY,
		capture INTEGER NOT NULL DEFAULT 0
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS member_frog_log (
		id         INTEGER PRIMARY KEY AUTOINCREMENT,
		uid        INTEGER NOT NULL,
		type       TEXT NOT NULL DEFAULT 'basic',
		at         TEXT NOT NULL,
		waited_for REAL
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS frog_spawn (
		cid      INTEGER PRIMARY KEY,
		interval INTEGER NOT NULL,
		persist  INTEGER NOT NULL,
		fuzzy    REAL NOT NULL
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS frog_messages (
		cid INTEGER NOT NULL,
		mid INTEGER NOT NULL,
		PRIMARY KEY (cid, mid)
	)
	""",
]

MESSAGE_KEY = "frog.message"
ENABLED_KEY = "frog.enabled"


@dataclass(slots=True)
class Spawn:
    """One ``frog_spawn`` row: a channel's spawn cadence config."""

    cid: int
    interval: int
    persist: int
    fuzzy: float


# -- settings --------------------------------------------------------------


async def get_message(settings: Settings) -> dict[str, Any] | None:
    """The frog spawn/capture message template, or None."""
    return await settings.get(MESSAGE_KEY)


async def set_message(settings: Settings, message: dict[str, Any]) -> None:
    """Persist the frog message template."""
    await settings.set(MESSAGE_KEY, message)


async def get_enabled(settings: Settings) -> bool:
    """Whether frogs are enabled."""
    return bool(await settings.get(ENABLED_KEY, False))


async def set_enabled(settings: Settings, val: bool) -> None:
    """Persist whether frogs are enabled."""
    await settings.set(ENABLED_KEY, val)


# -- inventory (frog holdings over the generic ledger) ----------------------


@dataclass(frozen=True, slots=True)
class FrogItem:
    """One frog inventory item: a species in a state.

    The generic inventory's typed identity (``cazzubot.inventory``): ``key``
    derives the stored string from two enum values — never a literal at
    call sites; ``parse`` is the read-side inverse, used once at the DB
    boundary. Item *definitions* stay in code (``species.py``); this only
    identifies a stack.
    """

    species: FrogItemKey
    state: FrogState

    @property
    def key(self) -> str:
        """The derived inventory storage string for this frog stack."""
        return frog_item_key(self.species, self.state)

    @classmethod
    def parse(cls, key: str) -> FrogItem:
        """Build a FrogItem from a stored inventory item string."""
        _, species, state = key.split(":")
        return cls(species=FrogItemKey(species), state=FrogState(state))


async def get_inventory(
    db: Database,
    uid: int,
    species_key: FrogItemKey,
    state: FrogState = FrogState.NORMAL,
) -> int:
    """A member's stack of ``species`` in ``state``."""
    return await inventory.get(db, uid, FrogItem(species_key, state))


async def modify_inventory(
    db: Database,
    uid: int,
    species_key: FrogItemKey,
    state: FrogState,
    modify: int,
) -> None:
    """Add (or subtract) frogs of a species/state; stacks prune at zero."""
    await inventory.modify(db, uid, FrogItem(species_key, state), modify)


async def inventory_rows(
    db: Database, uid: int
) -> list[tuple[FrogItemKey, FrogState, int]]:
    """A member's whole frog inventory: [(species_key, state, qty)]."""
    rows = await inventory.rows(db, uid, prefix="frog:")
    return [
        (item.species, item.state, qty)
        for item, qty in ((FrogItem.parse(k), q) for k, q in rows)
    ]


async def total_inventory(db: Database, uid: int) -> int:
    """Every frog a member holds, across species and states."""
    return await inventory.total(db, uid, prefix="frog:")


# -- member_frog (lifetime capture counter) --------------------------------


async def modify_capture(db: Database, uid: int, modify: int) -> None:
    """Add (or subtract) a member's lifetime capture counter."""
    await db.execute(
        """
		INSERT INTO member_frog (uid, capture)
		VALUES (?, ?)
		ON CONFLICT (uid) DO UPDATE SET
			capture = member_frog.capture + excluded.capture
		""",
        uid,
        modify,
    )


async def lifetime_ranked(db: Database) -> list[tuple[int, int, int]]:
    """All members ranked by lifetime captures: [(rank, uid, capture)]."""
    rows = await db.fetchall(
        """
		SELECT uid, capture AS cnt
		FROM member_frog
		ORDER BY capture DESC
		"""
    )
    return rank_rows([dict(r) for r in rows], "cnt")


async def sync_with_frog_logs(db: Database) -> None:
    """Rebuild lifetime capture counts from the frog logs."""
    await db.execute(
        """
		UPDATE member_frog
		SET capture = (
			SELECT COUNT(*)
			FROM member_frog_log
			WHERE member_frog_log.uid = member_frog.uid
		)
		"""
    )


async def season_reset_frogs(db: Database) -> None:
    """Quarterly: every frog becomes a Basic Frog ("use it or lose it").

    Owner rule (2026-08-28): at season end species identity and buffs
    do not carry over. Every non-basic stack (normal OR frozen) folds
    into ``frog:basic:normal``, then Basic's own soft reset folds the
    normal stack into frozen (10->3 exp). After a reset a member holds
    ``frog:basic:frozen`` only. Idempotent: a second run finds no
    non-basic stacks and no basic-normal stacks to fold.
    """
    basic_normal = FrogItem(FrogItemKey.BASIC, FrogState.NORMAL)
    basic_frozen = FrogItem(FrogItemKey.BASIC, FrogState.FROZEN)
    for species in SPECIES:
        if species.key is FrogItemKey.BASIC:
            continue
        await inventory.move_all(
            db, FrogItem(species.key, FrogState.NORMAL), basic_normal
        )
        await inventory.move_all(
            db, FrogItem(species.key, FrogState.FROZEN), basic_normal
        )
    await inventory.move_all(db, basic_normal, basic_frozen)


# -- member_frog_log -------------------------------------------------------


async def add_capture_log(
    db: Database,
    uid: int,
    at: pendulum.DateTime,
    *,
    waited_for: float,
    species_key: FrogItemKey,
) -> None:
    """Log one capture with the species and wait time."""
    await db.execute(
        """
		INSERT INTO member_frog_log (uid, type, at, waited_for)
		VALUES (?, ?, ?, ?)
		""",
        uid,
        species_key.value,
        at.isoformat(),
        waited_for,
    )


async def seasonal_ranked(
    db: Database, year: int, season: int
) -> list[tuple[int, int, int]]:
    """Members' captures this season, ranked: [(rank, uid, capture_count)]."""
    start, end = season_bounds(year, season)
    rows = await db.fetchall(
        """
		SELECT uid, COUNT(*) AS cnt
		FROM member_frog_log
		WHERE at >= ? AND at < ?
		GROUP BY uid
		ORDER BY cnt DESC
		""",
        start,
        end,
    )
    return rank_rows([dict(r) for r in rows], "cnt")


async def seasonal_captures(
    db: Database, uid: int, year: int, season: int
) -> int:
    """A member's captures within a single season."""
    start, end = season_bounds(year, season)
    val = await db.fetchval(
        """
		SELECT COUNT(*)
		FROM member_frog_log
		WHERE uid = ? AND at >= ? AND at < ?
		""",
        uid,
        start,
        end,
    )
    return int(val or 0)


async def seasonal_total_members(
    db: Database, year: int, season: int
) -> int:
    """How many distinct members captured frogs in a season."""
    start, end = season_bounds(year, season)
    val = await db.fetchval(
        """
		SELECT COUNT(DISTINCT uid)
		FROM member_frog_log
		WHERE at >= ? AND at < ?
		""",
        start,
        end,
    )
    return int(val or 0)


async def total_members(db: Database) -> int:
    """How many members have a capture-counter row."""
    val = await db.fetchval("SELECT COUNT(*) FROM member_frog")
    return int(val or 0)


# -- frog_spawn ------------------------------------------------------------


async def upsert_spawn(
    db: Database, cid: int, interval: int, persist: int, fuzzy: float
) -> None:
    """Upsert a channel's spawn cadence config."""
    await db.execute(
        """
		INSERT INTO frog_spawn (cid, interval, persist, fuzzy)
		VALUES (?, ?, ?, ?)
		ON CONFLICT (cid) DO UPDATE SET
			interval = excluded.interval,
			persist = excluded.persist,
			fuzzy = excluded.fuzzy
		""",
        cid,
        interval,
        persist,
        fuzzy,
    )


async def clear_spawns(db: Database) -> None:
    """Delete every spawn cadence config."""
    await db.execute("DELETE FROM frog_spawn")


async def get_spawns(db: Database) -> list[Spawn]:
    """All spawn cadence configs."""
    return await db.fetch_models(
        Spawn, "SELECT cid, interval, persist, fuzzy FROM frog_spawn"
    )


async def add_frog_message(db: Database, cid: int, mid: int) -> None:
    """Track a spawned frog's message id (for the boot dangling-message sweep)."""
    await db.execute(
        "INSERT OR IGNORE INTO frog_messages (cid, mid) VALUES (?, ?)",
        cid,
        mid,
    )


async def get_frog_messages(db: Database) -> list[tuple[int, int]]:
    """All tracked (channel id, frog message id) pairs."""
    rows = await db.fetchall("SELECT cid, mid FROM frog_messages")
    return [(row["cid"], row["mid"]) for row in rows]


async def drop_frog_message(db: Database, cid: int, mid: int) -> None:
    """Forget a frog message (deleted, cleaned up, or no longer a frog)."""
    await db.execute(
        "DELETE FROM frog_messages WHERE cid = ? AND mid = ?",
        cid,
        mid,
    )
