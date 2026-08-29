"""Item definitions registry — separates items from entities.

The inventory *ledger* (``cazzubot/inventory.py``) only counts holdings by
their stored ``item_id`` string; it knows nothing about what an item *is*.
This module is the **definitions layer**: what an item is (its id, display
name, icon) and how it behaves (its consume handler), keyed by the immutable
``item_id`` oracle.

Separation of concerns across the game's two players-visible concepts:

- **Entity** (e.g. a frog) — a world/spawn object with its own behavior
  (spawn cadence, catch effect). Catching one may grant items.
- **Item** — a stackable inventory object (display name, icon, consume
  behavior), owned by the plugin(s) that define it.

Item definitions are **code-declared**: a plugin declares an ``item_decl``
enum whose members are the code references and whose values are :class:`Item`
instances carrying an explicit, immutable ``item_id`` (the durable oracle —
renaming the enum member is free; changing ``item_id`` is a migration). The
registry resolves by id **independent of plugin enablement**, so disabling a
plugin deprecates its active *behavior* (spawns/commands) without taking its
items out of inventory: an item id whose declaring module is still present
keeps resolving. Only when a provider is truly gone (or removed from the
registry) does an id fall back to :data:`NOOP` — hidden, non-consumable.

Consumption is gated by a **per-provider flag** (`items_consumable`), separate
from the behavior-enablement flag, so a plugin can be behavior-disabled while
its existing holdings stay visible and consumable (or vice versa).

Call graph (self-documenting rule): ``bot.py`` registers a plugin's
``item_decl`` with :func:`register_items` at plugin load and unregisters it at
unload (both independent of behavior enablement); ``/inventory consume`` and
``/inventory view`` resolve ids through ``bot.items.item_for``. The registry
is module-global (like the asset/settings registries), exposed as ``bot.items``.

Depends on: the owning plugins' declaration enums (e.g. ``FrogItems``) and
``assets`` (``icon_asset`` members). Depended on by: ``bot`` (register /
unregister) and the ``inventory`` plugin (view / consume).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Item:
    """One inventory item definition.

    - ``item_id`` — the **immutable oracle**: this exact string is what's
      stored in ``inventory.item``. Never rename without a migration.
    - ``display_name`` — mutable, user-facing (inventory/profile).
    - ``icon`` — the static glyph rendered inline in ``/inventory`` (an
      emoji tag or URL).
    - ``description`` — **required** user-facing prose: the body of the
      item's info card (``/inventory info``). Every item must carry one.
    - ``icon_asset`` — optional EMOJI-kind asset member whose published
      ``<:name:id>`` reference *replaces* ``icon`` at render time (and
      becomes the info card's thumbnail); falls back to ``icon`` while the
      asset is unpublished (get() -> None).
    - ``consume`` — optional item-owned behavior when consumed (None = not
      directly consumable). Signature: ``async (bot, uid, amount) -> None``.
    - ``fields`` — optional ordered (label, text) pairs rendered as labeled
      embed fields on the info card (e.g. ``("On consumption", ...)``).
      Pure presentation — the underlying values stay in the owning
      plugin's own data, never baked into the item as structured fields.
    """

    item_id: str
    display_name: str
    icon: str
    description: str
    icon_asset: Enum | None = None
    consume: Callable[["CazzuBot", int, int], Awaitable[None]] | None = (
        None
    )
    fields: tuple[tuple[str, str], ...] = ()


# A sentinel representing "no such item definition" — displayed as nothing,
# refused consumption. Uses the same runtime semantics as a resolved item so
# callers never see an exception for a stale id.
NOOP = Item(
    item_id="noop", display_name="", icon="", description="", consume=None
)


# -- registry (module-global, exposed as bot.items) -------------------------

_ITEMS: dict[str, Item] = {}
_PROVIDER: dict[str, str] = {}  # item_id -> provider plugin name
_CONSUMABLE: dict[
    str, bool
] = {}  # provider name -> can items be consumed?


def register_items(provider: str, enum: type[Enum]) -> None:
    """Register every member of ``enum`` as an item owned by ``provider``.

    Idempotent: re-registering replaces the entries, so a hot-reloaded plugin
    can resubmit. Does not touch ``_CONSUMABLE`` — that's set via
    :func:`set_consumable` from the provider's ``items_consumable`` default.
    """
    for member in enum:
        item: Item = member.value
        _ITEMS[item.item_id] = item
        _PROVIDER[item.item_id] = provider
    _log.info("registered %d item(s) for %s", len(enum), provider)


def unregister_items(provider: str) -> None:
    """Drop every item the provider registered (its plugin unloaded)."""
    gone = [iid for iid, prov in _PROVIDER.items() if prov == provider]
    for iid in gone:
        _ITEMS.pop(iid, None)
        _PROVIDER.pop(iid, None)
    _CONSUMABLE.pop(provider, None)
    if gone:
        _log.info("unregistered %d item(s) for %s", len(gone), provider)


def set_consumable(provider: str, value: bool) -> None:
    """Set the provider's item-consumption flag (independent of behavior)."""
    _CONSUMABLE[provider] = value


def provider_for(item_id: str) -> str | None:
    """The plugin that owns ``item_id`` (None when unknown)."""
    return _PROVIDER.get(item_id)


def item_for(item_id: str) -> Item:
    """Resolve ``item_id`` to its Item, or :data:`NOOP` when unknown.

    Returns :data:`NOOP` (never None, never raises) so an id whose provider
    is unregistered/gone degrades cleanly instead of breaking the inventory
    view or a consume request.
    """
    return _ITEMS.get(item_id, NOOP)


def consumable(item_id: str) -> bool:
    """Whether ``item_id`` may currently be consumed.

    Gated by the owning provider's ``items_consumable`` flag; unknown ids
    (or providers without a flag) are not consumable.
    """
    provider = _PROVIDER.get(item_id)
    if provider is None:
        return False
    return _CONSUMABLE.get(provider, False)


def _is_resolved(item: Item) -> bool:
    """True when ``item`` is a real definition, not the NOOP sentinel."""
    return item is not NOOP and item.item_id != "noop"


class Items:
    """The items registry as a bot service (``bot.items``).

    Owns nothing schema-wise (items are code, not tables). Wraps the
    module-level registry for consumers that hold the bot: register/unregister
    from plugin lifecycle, resolve ids for the inventory UI and consume.
    """

    def __init__(self, bot: "CazzuBot") -> None:
        """Bind to ``bot`` (the registry is module-global)."""
        self.bot = bot

    def register(self, provider: str, enum: type[Enum]) -> None:
        """Register the provider's item enum."""
        register_items(provider, enum)

    def unregister(self, provider: str) -> None:
        """Drop the provider's items."""
        unregister_items(provider)

    def set_consumable(self, provider: str, value: bool) -> None:
        """Set the provider's item-consumption flag."""
        set_consumable(provider, value)

    def item_for(self, item_id: str) -> Item:
        """The Item for ``item_id``, or :data:`NOOP` when unknown."""
        return item_for(item_id)

    def resolved(self, item_id: str) -> bool:
        """Whether ``item_id`` maps to a real definition (not NOOP)."""
        return _is_resolved(self._lookup(item_id))

    def consumable(self, item_id: str) -> bool:
        """Whether ``item_id`` may currently be consumed."""
        return consumable(item_id)

    def _lookup(self, item_id: str) -> Item:
        return _ITEMS.get(item_id, NOOP)
