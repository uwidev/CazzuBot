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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

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
    def key(self) -> str:
        """The derived storage string for this item."""
        ...


@dataclass(frozen=True, slots=True)
class ItemView:
    """How one inventory item is presented in a grid slot.

    The renderer's output: an inline ``icon`` (a Discord emoji, the only
    thing that renders inline in an embed field) and a human ``label`` (the
    species/item name and state). Kept framework-free so the core stays
    hikari-clean.
    """

    icon: str
    label: str


Renderer = Callable[[str, int], ItemView]
"""A presenter for one item namespace: ``(stored_item_key, qty) -> ItemView``.

The core does not know what any namespace's items mean — the renderer for a
``frog:...`` key parses it back into a species + state and renders its name/
icon. The default (:data:`_default_renderer`) shows the raw key so an
unknown or unregistered namespace degrades gracefully instead of crashing.
"""


# The namespace-keyed renderer registry — populate via register_renderer
# (plugins do this in ``on_load``), so the generic inventory UI can present
# any item type without the core importing that plugin (the effects-registry
# pattern: no lookup table of the core's own, no plugin coupling).
_RENDERERS: dict[str, Renderer] = {}


def register_renderer(prefix: str, renderer: Renderer) -> None:
    """Make ``prefix`` (e.g. ``"frog"``) renderable by ``renderer``.

    Idempotent: re-registering replaces the entry, so a hot-reloaded plugin
    can resubmit without a boot.
    """
    _RENDERERS[prefix] = renderer


def unregister_renderer(prefix: str) -> None:
    """Drop ``prefix``'s renderer (its plugin unloaded). A no-op if absent."""
    _RENDERERS.pop(prefix, None)


def renderer_for(prefix: str) -> Renderer:
    """The renderer for ``prefix``, falling back to the default.

    Unregistered namespaces (or a plugin that registered then unloaded) fall
    back to :data:`_default_renderer`, so the inventory view never breaks on
    an item kind it doesn't know.
    """
    return _RENDERERS.get(prefix, _default_renderer)


def _default_renderer(item_key: str, _qty: int) -> ItemView:
    return ItemView(icon="", label=item_key)


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


def _prefix_where(
    uid: int, prefix: str | None
) -> tuple[str, tuple[object, ...]]:
    """The shared ``WHERE uid = ? [AND item LIKE ?]`` fragment."""
    where = "uid = ?"
    args: tuple[object, ...] = (uid,)
    if prefix is not None:
        where += " AND item LIKE ?"
        args += (prefix + "%",)
    return where, args


async def rows(
    db: Database, uid: int, *, prefix: str | None = None
) -> list[tuple[str, int]]:
    """A member's non-empty stacks: [(item, qty)], ordered by item.

    ``prefix`` filters to one namespace (e.g. ``"frog:"``) so consumers
    sharing the table only see their own items; the returned item strings
    are parsed back to typed identities by the caller (once, at the read
    boundary).
    """
    where, args = _prefix_where(uid, prefix)
    rows_ = await db.fetchall(
        f"SELECT item, qty FROM inventory WHERE {where} AND qty > 0 "
        "ORDER BY item",
        *args,
    )
    return [(row["item"], row["qty"]) for row in rows_]


async def rows_indexed(
    db: Database, uid: int, *, prefix: str | None = None
) -> list[tuple[int, str, int]]:
    """A member's stacks with deterministic 1-based slot indices.

    Returns ``[(slot, item, qty)]`` where ``slot`` is the position in
    :func:`rows`' ``ORDER BY item`` order. Indices are **derived, not
    stored** — the same ordering maps a grid slot back to its item, so a
    future ``/inventory consume <slot>`` can resolve ``slot`` by re-computing
    this same order. Stable across calls for an unchanged inventory.
    """
    return [
        (slot, item, qty)
        for slot, (item, qty) in enumerate(
            await rows(db, uid, prefix=prefix), start=1
        )
    ]


async def total(
    db: Database, uid: int, *, prefix: str | None = None
) -> int:
    """Every item a member holds in ``prefix`` (all items when None)."""
    where, args = _prefix_where(uid, prefix)
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

    schema = _SCHEMA

    def __init__(self, bot: "CazzuBot") -> None:
        """Bind the service to ``bot`` (operations run on ``bot.db``)."""
        self.bot = bot

    async def add(self, uid: int, item: InventoryKey, amount: int) -> None:
        """Add (or subtract) ``amount`` from a member's ``item`` stack."""
        return await add(self.bot.db, uid, item, amount)

    async def get(self, uid: int, item: InventoryKey) -> int:
        """A member's stack of ``item`` (0 when absent)."""
        return await get(self.bot.db, uid, item)

    async def rows(
        self, uid: int, *, prefix: str | None = None
    ) -> list[tuple[str, int]]:
        """A member's non-empty stacks, optionally filtered by ``prefix``."""
        return await rows(self.bot.db, uid, prefix=prefix)

    async def rows_indexed(
        self, uid: int, *, prefix: str | None = None
    ) -> list[tuple[int, str, int]]:
        """A member's stacks with deterministic 1-based slot indices."""
        return await rows_indexed(self.bot.db, uid, prefix=prefix)

    def register_renderer(self, prefix: str, renderer: Renderer) -> None:
        """Make ``prefix`` renderable by ``renderer`` (idempotent)."""
        register_renderer(prefix, renderer)

    def unregister_renderer(self, prefix: str) -> None:
        """Drop ``prefix``'s renderer (no-op if absent)."""
        unregister_renderer(prefix)

    def renderer_for(self, prefix: str) -> Renderer:
        """The renderer for ``prefix``, defaulting to the raw-key view."""
        return renderer_for(prefix)

    async def total(self, uid: int, *, prefix: str | None = None) -> int:
        """Total quantity a member holds, optionally within ``prefix``."""
        return await total(self.bot.db, uid, prefix=prefix)

    async def move_all(self, src: InventoryKey, dst: InventoryKey) -> None:
        """Fold every member's ``src`` stack into ``dst``."""
        return await move_all(self.bot.db, src, dst)
