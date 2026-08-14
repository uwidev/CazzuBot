"""Generic inventory — a per-member, per-item quantity ledger.

One shared table for every "player × item × stack" need (frog species×state
today; badges-as-vanity, shop items, combine ingredients later). Items are
identified by a **typed key** (:class:`InventoryKey`) whose stored string
is *derived* — never a hand-written literal at call sites — so the ledger
stays generic while references stay LSP-checked (the asset_key / EffectKey
pattern). Item *definitions* (what an item is, its effects, art) live in
each plugin's code registry; this store only counts them.

Call graph (per the self-documenting rule): the frogs plugin is the current
caller — ``plugins/frogs/db.py`` wraps these functions with its typed
``FrogItem`` identity; the quarterly freeze goes through :func:`move_all`.
Future consumers (badges-as-items, shop) call them directly.

Rows are holdings, not history: add/subtract quantities here; audit trails
stay in per-feature logs (e.g. ``member_frog_log``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from cazzubot.db import Database

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)

_SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS inventory (
		uid  INTEGER NOT NULL,
		item TEXT NOT NULL,
		qty  INTEGER NOT NULL DEFAULT 0,
		PRIMARY KEY (uid, item)
	)
	""",
]

# Public alias for tooling that needs the DDL without instantiating the class.
SCHEMA = _SCHEMA


class InventoryKey(Protocol):
    """A typed item identity.

    Implementations expose ``key`` — the derived storage string (e.g. the
    frogs ``FrogItem`` composite builds ``"frog:<species>:<state>"`` from
    two enum values in one place). Callers pass the typed object; the
    store only ever sees the derived string.
    """

    @property
    def key(self) -> str: ...


async def add(
    db: Database, uid: int, item: InventoryKey, amount: int
) -> None:
    """Add (or subtract, with negative ``amount``) from a member's stack.

    A stack that reaches zero or below is pruned — zero-quantity rows never
    accumulate. No error on negative results: validation of "can you afford
    this" stays with the caller (frogs checks balances before consuming).
    """
    await db.execute(
        """
		INSERT INTO inventory (uid, item, qty) VALUES (?, ?, ?)
		ON CONFLICT (uid, item) DO UPDATE SET
			qty = inventory.qty + excluded.qty
		""",
        uid,
        item.key,
        amount,
    )
    await db.execute(
        "DELETE FROM inventory WHERE uid = ? AND item = ? AND qty <= 0",
        uid,
        item.key,
    )


async def get(db: Database, uid: int, item: InventoryKey) -> int:
    """A member's stack of ``item`` (0 when absent)."""
    val = await db.fetchval(
        "SELECT qty FROM inventory WHERE uid = ? AND item = ?",
        uid,
        item.key,
    )
    return int(val or 0)


async def rows(
    db: Database, uid: int, *, prefix: str | None = None
) -> list[tuple[str, int]]:
    """A member's non-empty stacks: [(item, qty)], ordered by item.

    ``prefix`` filters to one namespace (e.g. ``"frog:"``) so consumers
    sharing the table only see their own items; the returned item strings
    are parsed back to typed identities by the caller (once, at the read
    boundary).
    """
    where = "uid = ? AND qty > 0"
    args: tuple[object, ...] = (uid,)
    if prefix is not None:
        where += " AND item LIKE ?"
        args += (prefix + "%",)
    rows_ = await db.fetchall(
        f"SELECT item, qty FROM inventory WHERE {where} ORDER BY item",
        *args,
    )
    return [(row["item"], row["qty"]) for row in rows_]


async def total(
    db: Database, uid: int, *, prefix: str | None = None
) -> int:
    """Every item a member holds in ``prefix`` (all items when None)."""
    where = "uid = ?"
    args: tuple[object, ...] = (uid,)
    if prefix is not None:
        where += " AND item LIKE ?"
        args += (prefix + "%",)
    val = await db.fetchval(
        f"SELECT COALESCE(SUM(qty), 0) FROM inventory WHERE {where}",
        *args,
    )
    return int(val or 0)


async def move_all(
    db: Database, src: InventoryKey, dst: InventoryKey
) -> None:
    """Fold every member's stack of ``src`` into ``dst``, then drop ``src``.

    The generic primitive behind the quarterly freeze (normal → frozen per
    species). Idempotent: with no ``src`` rows it is a no-op.
    """
    await db.execute(
        """
		INSERT OR IGNORE INTO inventory (uid, item, qty)
		SELECT uid, ?, 0 FROM inventory WHERE item = ?
		""",
        dst.key,
        src.key,
    )
    await db.execute(
        """
		UPDATE inventory
		SET qty = qty + (
			SELECT COALESCE(SUM(qty), 0)
			FROM inventory AS folding
			WHERE folding.uid = inventory.uid AND folding.item = ?
		)
		WHERE item = ?
		""",
        src.key,
        dst.key,
    )
    await db.execute("DELETE FROM inventory WHERE item = ?", src.key)


class Inventory:
    """The inventory service on the bot (``bot.inventory``).

    Owns the schema (run at boot like settings/scheduler/assets) and
    delegates the same operations against ``bot.db`` for consumers that
    hold the bot rather than a Database.
    """

    def __init__(self, bot: "CazzuBot") -> None:
        self.bot = bot

    @property
    def schema(self) -> list[str]:
        return _SCHEMA

    async def add(self, uid: int, item: InventoryKey, amount: int) -> None:
        return await add(self.bot.db, uid, item, amount)

    async def get(self, uid: int, item: InventoryKey) -> int:
        return await get(self.bot.db, uid, item)

    async def rows(
        self, uid: int, *, prefix: str | None = None
    ) -> list[tuple[str, int]]:
        return await rows(self.bot.db, uid, prefix=prefix)

    async def total(self, uid: int, *, prefix: str | None = None) -> int:
        return await total(self.bot.db, uid, prefix=prefix)

    async def move_all(self, src: InventoryKey, dst: InventoryKey) -> None:
        return await move_all(self.bot.db, src, dst)
