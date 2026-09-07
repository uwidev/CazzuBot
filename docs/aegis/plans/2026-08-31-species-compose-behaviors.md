2026-08-31 — Species / Items compose behaviors (backlog D5)
===========================================================

Goal
----

Frog species should compose their own behavior by **writing code**, not by
declaring payload dataclasses in a registry: the species carries its
`catch`/`spawn` behavior as plain callables, items trigger the statuses they
decide on from written consume glue, and every value of a status effect
(chance, duration, role ids, reapply policy, priority) lives **on the status
class itself** — never at the call site.

This is the backlog item
`## 2026-08-31 — Species compose outcomes (rename follow-up)`
(docs/needs-rewrite/BACKLOG.md), tracked from D5/T8 of
`docs/aegis/plans/2026-08-31-effects-to-statuses-outcomes.md`.


Architecture
------------

The action pipeline becomes **one unified system with three declared
objects**, connected by direct awaited calls and the event bus:

~~~~ text
        Species (mob)              Item (inventory)              Status (state)
  spawn behavior ──────────▶  consume behavior ──────────▶   class-owned values
  catch behavior  ──grants──▶  (exp + statuses)     invokes▶ (register + store)
~~~~

 -  **Species** = the mob. `catch`/`spawn` fields are code (callables). No
    default: `catch=None` means **nothing happens** — the item is granted only
    if a catch behavior says so (the four catchable frogs declare the shared
    `grant_catch` helper; Cluster declares none). Helpers live **beside the
    species that uses them** (`plugins/frogs/behaviors.py`).
 -  **Item** = inventory/presentation. `consume` is the written-function seam
    (`(bot, uid, amount) -> None`, unchanged core `Item`); the frog item glue
    grants exp from the `frog_exp` oracle and triggers the status tuple the item
    declares. `Item` itself gains **no** new fields — the glue function IS the
    composition (bare-`Item`-literal convention from the memory stays).
 -  **Status** = a declared class owning its data: `key` (source identity),
    `name`, `seam`, `scope_kind`, `priority`, `duration`, `policy`, subclass
    value fields (`chance`, role ids), `describe()`, `apply()`. Statuses are
    **core** (`cazzubot/statuses.py`): any feature — a species, an item, a
    future command — registers a status and invokes it via `bot.statuses` +
    its `apply()`. Frog-specific status flesh lives in
    `plugins/frogs/statuses.py`.
 -  **Seam pull is the referee.** A pull reads every active contribution on
    its seam, maps each `source` back to its Status class, and folds by
    `priority` (highest wins; ties → lowest `source`). Sibling statuses stay
    **separate rows** (the store already stacks by `(scope, seam, source)`), so
    expiry of the winner reveals the next — the “fall back to Pog after
    Froggers expires” behavior **falls out for free** (no merge logic at
    write time).
 -  Sibling statuses are grouped **in code** (both reaction statuses subclass
    one `ReactionStatus`), never by an engine-enforced rule.
 -  Reapply policy (`EXTEND`/`REPLACE`) stays a **per-status** choice;
    `ReactionStatus` defaults to `EXTEND` (duration-only), a status that wants
    a hard refresh uses `REPLACE`. The old REPLACE/EXTEND *value-merge* logic in
    `ReactionOutcome.consume` is deleted (no values to merge — the class holds
    them).
 -  **Events/observers** stay on the existing bus: `FrogCapturedEvent`,
    `FrogConsumedEvent`, `StatusesClearedEvent` — unchanged semantics.
 -  **Info card** (“On consumption”) derives from the **status classes** the
    item declares (their `describe()` + the `frog_exp` oracle) — values stay
    single-source, no prose drift.

### Core `Status` (added to `cazzubot/statuses.py`)

~~~~ python
@dataclass(frozen=True, slots=True, kw_only=True)
class Status:
    """One status effect — the class owns its values.

    The store records the contribution; the class decides what it means.
    ``key`` is the source identity stored in ``status_contribution.source``
    (and in convergence job payloads). ``scope_kind`` pins where the status
    applies (member vs guild) and is enforced at ``apply`` time.
    """

    key: str
    name: str
    seam: SeamKey
    scope_kind: ScopeKind = ScopeKind.MEMBER
    priority: int = 0  # fold order on a shared seam (higher wins)
    duration: timedelta | None = None
    policy: ReapplyPolicy = ReapplyPolicy.EXTEND

    def describe(self) -> str:
        """Human summary for info cards (subclasses enrich)."""
        return self.name

    async def apply(
        self,
        bot: "CazzuBot",
        *,
        scope: Scope,
        provenance: str,
        now: pendulum.DateTime | None = None,
    ) -> None:
        """Invoke this status for ``scope``, granted by ``provenance``.

        The only payload the store sees is provenance: the granting item id.
        All other data (chance, window, role ids) lives on this class and is
        resolved at pull time via :func:`status_by_source`.
        """
        if scope.kind is not self.scope_kind:
            raise TypeError(
                f"status {self.key!r} is {self.scope_kind.value}-scoped, "
                f"got {scope.kind.value} scope"
            )
        await bot.statuses.publish(
            scope,
            self.seam,
            self.key,
            {"from": provenance},
            duration=self.duration,
            policy=self.policy,
            now=now,
        )
~~~~

Registry (same module):

~~~~ python
_STATUSES: dict[str, Status] = {}


def register_status(status: Status) -> None:
    """Register a status class by its ``key`` (idempotent; reload-safe)."""
    _STATUSES[status.key] = status


def status_by_source(source: str) -> Status | None:
    """The registered status for a contribution ``source`` (None when gone)."""
    return _STATUSES.get(source)


def statuses_for_seam(seam: str | SeamKey) -> list[Status]:
    """Every registered status feeding ``seam`` (sorted by source)."""
    seam_key = _key(seam)
    return sorted(
        (s for s in _STATUSES.values() if _key(s.seam) == seam_key),
        key=lambda s: s.key,
    )
~~~~

Note `_key` already exists in this module; `pendulum`/`timedelta`/`SeamKey`
are already imported.

### Frog statuses (`plugins/frogs/statuses.py`, new)

~~~~ python
"""Frog statuses — unique status effects, values owned by the class.

Stored strings tie to nothing outside this module: ``Status.key`` is the
contribution ``source``; ``FrogSeam`` is the seam the status fills. The old
``FrogStatus`` identity enum is gone — the status class IS the identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from cazzubot.statuses import (
    Scope,
    ScopeKind,
    Status,
    register_status,
    status_by_source,
    statuses_for_seam,
)

from .seams import FrogSeam


@dataclass(frozen=True, slots=True, kw_only=True)
class ReactionStatus(Status):
    """A reaction-chance status: consume grants the shared react seam."""

    chance: float
    cooldown_seconds: int = 10

    def describe(self) -> str:
        window = _describe_duration(self.duration)
        return (
            f"For {window}, a **{self.chance:.0%}** chance the bot "
            f"reacts to your messages with the froggers emoji "
            f"({self.cooldown_seconds}s cooldown)."
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleStatus(Status):
    """A role-grant status: the classy frog's external world consequence."""

    role_dev: int
    role_prod: int

    def role_id_for(self, guild_kind: str) -> int:
        """The concrete role id for the guild side (FROG.md's two ids)."""
        return (
            self.role_dev
            if guild_kind == "development"
            else self.role_prod
        )

    def describe(self) -> str:
        window = _describe_duration(self.duration)
        return f"Grants the **Classy** role for {window}."


def _describe_duration(duration: timedelta | None) -> str:
    """'1 hour' / '3 hours' / '1 minute' — the card prose for a window."""
    if duration is None:
        return "forever"
    total = duration.total_seconds()
    if total < 60:
        return "1 minute"
    if total < 3600:
        return f"{duration.seconds // 60} minutes"
    hours = duration.seconds // 3600
    return f"{hours} hour{'s' if hours != 1 else ''}"


# -- the frog statuses (one unique class per declared status) ----------

POG_REACTION = ReactionStatus(
    key="frog:blessing:pog",
    name="Blessing of the Pog Frog",
    seam=FrogSeam.FROG_REACTION,
    priority=1,  # the weaker sibling
    duration=timedelta(hours=1),
    chance=0.01,
)

FROGGERS_REACTION = ReactionStatus(
    key="frog:blessing:froggers",
    name="Blessing of the Froggers Frog",
    seam=FrogSeam.FROG_REACTION,
    priority=2,  # the stronger sibling (keep both rows; fallback on expiry)
    duration=timedelta(hours=1),
    chance=0.07,
)

CLASSY_ROLE = RoleStatus(
    key="frog:blessing:classy",
    name="Blessing of the Classy Frog",
    seam=FrogSeam.CLASSY_ROLE,
    duration=timedelta(hours=3),
    role_dev=1542294599358353430,
    role_prod=1542293782588952696,
)

_FROG_STATUSES = (POG_REACTION, FROGGERS_REACTION, CLASSY_ROLE)


def register_frog_statuses() -> None:
    """Register every frog status (idempotent; called at module bottom)."""
    for status in _FROG_STATUSES:
        register_status(status)


def classy_role_ids() -> frozenset[int]:
    """Every role id the classy statuses may grant (the converger's bound set)."""
    return frozenset(
        role_id
        for status in statuses_for_seam(FrogSeam.CLASSY_ROLE)
        if isinstance(status, RoleStatus)
        for role_id in (status.role_dev, status.role_prod)
    )


class RoleConverger:
    """World-reconciliation for the CLASSY_ROLE seam (roles on members).

    Registered via ``bot.statuses.register_converger`` at plugin load. The
    seam's active contributions are read as facts; each contribution's
    ``source`` is mapped back to its :class:`RoleStatus` to derive the
    concrete role id for the current guild kind. Idempotent by construction:
    adds missing, removes only the bound role ids that are no longer wanted.
    """

    def __init__(self, known_role_ids: frozenset[int]) -> None:
        """The roles this seam may remove — derived from :func:`classy_role_ids`."""
        self._known = known_role_ids

    async def __call__(
        self, bot: "CazzuBot", scope: Scope, seam: str
    ) -> None:
        if scope.kind is not ScopeKind.MEMBER:
            return
        contribs = await bot.statuses.list(scope, FrogSeam.CLASSY_ROLE)
        wanted: set[int] = set()
        for contrib in contribs:
            status = status_by_source(contrib.source)
            if not isinstance(status, RoleStatus):
                continue  # unknown/retired source — ignore, keep peace
            wanted.add(status.role_id_for(bot.config.guild_kind))
        try:
            member = await bot.rest.fetch_member(
                bot.config.guild_id, scope.id
            )
            current = set(member.role_ids)
        except Exception:
            _log.exception(
                "classy role converge: cannot fetch member %s", scope.id
            )
            return
        reason = "classy frog role status"
        for role_id in wanted - current:
            await bot.rest.add_role_to_member(
                bot.config.guild_id, scope.id, role_id, reason=reason
            )
        for role_id in (current & self._known) - wanted:
            await bot.rest.remove_role_from_member(
                bot.config.guild_id, scope.id, role_id, reason=reason
            )


register_frog_statuses()
~~~~

(`_log` import from `logging`; `"CazzuBot"` under `TYPE_CHECKING`.)

### Species (`plugins/frogs/species.py`)

~~~~ python
"""Frog species catalog — defined entirely in code.

The ``SPECIES`` registry is the single source of truth: names, rarity,
weights and art live here (no catalog table). A species is a **mob**: its
declaration composes its own behavior as code — the ``catch`` hook (what
happens when the frog is caught; nothing by default) and the ``spawn`` hook
(what replaces the catchable frog at spawn time). Capturing a frog grants
the item ONLY when the catch behavior does it; the species itself is never
an inventory item (items live in ``items.py``).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from cazzubot.models import FrogItemKey

from .assets import FrogAsset
from .behaviors import ClusterBurst, grant_catch

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

DEFAULT_SPECIES_KEY = FrogItemKey.BASIC

# the one shape every species behavior has: async code running with the bot
# plus whatever context it needs (the behavior picks its own kwargs)
Behavior = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class Species:
    """One mob — its behavior is the code it references.

    ``catch`` is the capture hook (None: nothing happens on capture —
    explicit per design; the catchable species declare :func:`grant_catch`).
    ``spawn`` is the spawn hook (None: the normal catchable path; Cluster
    declares :class:`ClusterBurst`). Helpers a behavior needs live beside
    that behavior (see ``behaviors.py``).
    """

    key: FrogItemKey
    name: str
    rarity: str
    description: str
    spawn_weight: float
    catch: Behavior | None
    spawn: Behavior | None
    art: FrogAsset | None


SPECIES: tuple[Species, ...] = (
    Species(
        key=FrogItemKey.BASIC,
        name="Basic Frog",
        rarity="common",
        description="The most normalest frog of them all.",
        spawn_weight=1000.0,
        catch=grant_catch,
        spawn=None,
        art=FrogAsset.FROG_BASIC,
    ),
    Species(
        key=FrogItemKey.POG,
        name="Pog Frog",
        rarity="uncommon",
        description="A frog with a pog.",
        spawn_weight=200.0,
        catch=grant_catch,
        spawn=None,
        art=FrogAsset.FROG_POG,
    ),
    Species(
        key=FrogItemKey.FROGGERS,
        name="Froggers Frog",
        rarity="rare",
        description="A frog with a poggers.",
        spawn_weight=50.0,
        catch=grant_catch,
        spawn=None,
        art=FrogAsset.FROG_FROGGERS,
    ),
    Species(
        key=FrogItemKey.CLASSY,
        name="Classy Frog",
        rarity="rare",
        description="A frog with rather refined tastes.",
        spawn_weight=200.0,
        catch=grant_catch,
        spawn=None,
        art=FrogAsset.FROG_CLASSY,
    ),
    Species(
        key=FrogItemKey.CLUSTER,
        name="Cluster Frog",
        rarity="special",
        description="Be careful with this one… she's… spawning!",
        spawn_weight=300.0,
        catch=None,  # cannot be caught — the spawn hook replaces it
        spawn=ClusterBurst(),
        art=None,
    ),
)

_BY_KEY: dict[FrogItemKey, Species] = {
    species.key: species for species in SPECIES
}


def by_key(key: FrogItemKey) -> Species | None:
    """The species for ``key`` (None when unknown)."""
    return _BY_KEY.get(key)


def roll_species(rng: random.Random | None = None) -> Species:
    """Pick a species by ``spawn_weight``; ``rng`` seeds the roll for tests."""
    chooser = rng or random
    return chooser.choices(
        SPECIES, weights=[species.spawn_weight for species in SPECIES]
    )[0]
~~~~

### Behaviors (`plugins/frogs/behaviors.py`, new — the code the species compose)

Holds the shared catch grant and the Cluster spawn burst, plus their local
helpers. This file may import hikari (controller-shaped — like
`factory.py`, it is the spawn/capture + embed edge); `species.py` itself
stays hikari-free, it only imports the *values*.

~~~~ python
"""Frog species behaviors — the code species compose.

Species compose their behavior by writing code; the shared behaviors below
are the helpers a species may compose. Each is written next to its local
helpers (the Cluster burst keeps its zone math + child-spawn tracking here).

Two behaviors ship:
- ``grant_catch`` — the default catch of every catchable species: +1 of the
  species' item to the catcher's inventory + the capture announcement embed.
  Species that just grant their item on capture compose *exactly this*
  (``catch=grant_catch``). A species that wants a custom catch writes its
  own behavior beside itself (nothing here forces a shape on it).
- ``ClusterBurst`` — the spawn hook for Cluster Frog: replaces the
  catchable frog at spawn time by bursting 4–10 Basic frogs into the
  channels around the spawn channel. Its child-spawning implementation is
  injected at plugin load (outcomes → factory would cycle; the plugin
  bridges), so this module never imports the factory.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast

import hikari
import pendulum

from cazzubot import templates, utils
from cazzubot.models import FrogState, MemberSnapshot, FrogItemKey

from . import db as frog_db

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot
    from .species import Species

_log = logging.getLogger(__name__)

_CAPTURE_COLOR = hikari.Color.from_hex_code("#a2dcf7")

# hikari-free channel-type check (hikari.ChannelType.GUILD_TEXT == 0)
_GUILD_TEXT = 0


# -- catch behaviors ------------------------------------------------------


async def grant_catch(
    bot: "CazzuBot",
    *,
    uid: int,
    member: MemberSnapshot,
    species: "Species",
    now: Any,  # pendulum.DateTime
    cid: int,
) -> hikari.Message:
    """The every-catchable-species catch: +1 item and the capture embed.

    Composed by each catchable species ('species.catch = grant_catch').
    The granted item is derived from the species key (``frog:<key>:normal``
    — the frozen state is only reachable by season rollover, so a fresh
    capture always grants the normal item).  The embed comes from the
    configured ``frog.message`` template when set, else the built-in.
    """
    item_id = frog_db.FrogItem(species.key, FrogState.NORMAL).key
    await bot.inventory.add(uid, item_id)

    frog_cnt_total = await frog_db.total_inventory(bot.db, uid)
    seasonal = await frog_db.seasonal_captures(
        bot.db, uid, now.year, utils.month2season(now.month)
    )
    msg_json = await frog_db.get_message(bot.settings) or {}
    if msg_json:
        utils.deep_map(
            msg_json,
            formatter,
            member=member,
            frog_cnt_old=frog_cnt_total - 1,
            frog_cnt_new=frog_cnt_total,
            seasonal_cap_old=seasonal - 1,
            seasonal_cap_new=seasonal,
            species=species.name,
            species_art=(
                (await bot.assets.get(species.art) or "")
                if species.art is not None
                else ""
            ),
        )
        payload = templates.build_payload(msg_json)
    else:
        payload = {"embed": await _default_capture_embed(
            bot, member, species, frog_cnt_total, seasonal)}
    sent = await bot.rest.create_message(
        cid,
        **payload,
        user_mentions=(
            [uid]
            if msg_json.get("allowed_mentions") is not False
            else hikari.UNDEFINED
        ),
        role_mentions=hikari.UNDEFINED,
        mentions_everyone=hikari.UNDEFINED,
    )
    utils.schedule_delete(bot, cid, int(sent.id), 7)
    return sent


async def _default_capture_embed(...) -> hikari.Embed:
    # moved verbatim from plugins/frogs/factory.py (see factory diff below)
    ...


# -- spawn behaviors ------------------------------------------------------


class ClusterBurst:
    """The Cluster species' spawn behavior: burst Basic frogs nearby.

    An instance is composed into ``SPECIES`` (Cluster's ``spawn``). The
    child-spawning implementation is injected by the plugin at load
    (``bot spawn_impl = factory.spawn_and_wait``); this module never
    imports the factory, keeping the graph acyclic. Children run as
    tracked background tasks so the scheduled spawn fires immediately.
    """

    def __init__(self) -> None:
        self.spawn_impl: Callable[..., Awaitable[bool]] | None = None
        self._background: set[asyncio.Task[Any]] = set()

    async def __call__(
        self,
        bot: "CazzuBot",
        *,
        cid: int,
        guild_id: int,
        persist: int,
        now: Any,
    ) -> None:
        """Explode: 4–6 Basic frogs into the text channels around ``cid``."""
        if self.spawn_impl is None:
            _log.error("ClusterBurst has no spawn_impl — plugin on_load missed")
            return
        zone = await self._zone(bot, guild_id, cid)
        if not zone:
            _log.warning("cluster spawn channel %s outside text channels", cid)
            return
        count = random.randint(4, 6)
        targets = [random.choice(zone) for _ in range(count)]
        _log.info("cluster frog bursts %d basic(s) across %d channel(s)", count, len(zone))
        for target in targets:
            self._start_child(bot, persist, target)
            await asyncio.sleep(0.75)  # the rate-limit guard

    async def _zone(self, bot: "CazzuBot", guild_id: int, cid: int) -> list[tuple[int, int]]:
        """(channel_id, position) of text channels ±2 around ``cid``."""
        channels = await bot.rest.fetch_guild_channels(guild_id)
        texts = [
            (int(channel.id), int(getattr(channel, "position", 0) or 0))
            for channel in channels
            if getattr(channel, "type", None) == _GUILD_TEXT
        ]
        texts.sort(key=lambda entry: (entry[1], entry[0]))
        ids = [entry[0] for entry in texts]
        if cid not in ids:
            return []
        index = ids.index(cid)
        return texts[max(0, index - 2) : index + 3]

    def _start_child(self, bot: "CazzuBot", persist: int, target: tuple[int, int]) -> None:
        """Fire one child Basic-frog spawn as a tracked background task."""
        impl = self.spawn_impl
        if impl is None:
            _log.error("ClusterBurst has no spawn_impl — plugin on_load missed")
            return
        task = asyncio.create_task(
            cast(
                "Coroutine[Any, Any, bool]",
                impl(bot, persist, cid=target[0], species_key=FrogItemKey.BASIC),
            )
        )
        self._background.add(task)
        task.add_done_callback(self._background.discard)
~~~~

(`formatter`, `cast`, `templates`, `utils` imports are the same ones
`factory.py` uses today — copy the embed/helpers over verbatim from
`factory.py`; only the *class* shape is new.)

### Items (`plugins/frogs/items.py`) rewrite

The per-item consume glue becomes the item's own written composition: the
item grants its exp (item-owned, the `frog_exp` oracle) and triggers the
statuses its own declaration names. The `_SPECIES_OUTCOMES` dict and the
funnel `_consume_item`-over-payloads are deleted; the info blurb reads the
status classes.

~~~~ python
"""Frog items — the *item* half of the frog split.

``species.py`` is the capturable entity (its behavior: spawn, catch).
This module is the **frog item**: what a caught frog *is* as an inventory
object — immutable ``item_id`` (the oracle), display name/icon, the
description card, and its **item-owned consume** behavior.

What consuming an item does is the ITEM's decision and is written as code:
the per-item glue grants seasonal exp from the ``frog_exp`` oracle and
invokes the statuses the item declares (e.g. ``POG_REACTION``). Statuses are
unique classes owning their own values (``plugins/frogs/statuses.py``);
the item just *names* the ones it triggers — no outbound payload objects,
no registry indirection.
"""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING

import pendulum

from cazzubot import Item
from cazzubot.models import FrogState, FrogItemKey, MemberExpLogSourceEnum
from cazzubot.statuses import Scope, Status

from plugins.experience import db as exp_db

from .assets import FrogAsset
from .events import FrogConsumedEvent
from .statuses import (
    POG_REACTION,
    FROGGERS_REACTION,
    CLASSY_ROLE,
)

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

# species × state -> exp per unit (owner-tunable). The single source for
# both the consume glue and the catalog/info display.
_SPECIES_EXP: dict[FrogItemKey, dict[FrogState, int]] = {
    FrogItemKey.BASIC: {FrogState.NORMAL: 10, FrogState.FROZEN: 3},
    FrogItemKey.POG: {FrogState.NORMAL: 30, FrogState.FROZEN: 15},
    FrogItemKey.FROGGERS: {FrogState.NORMAL: 300, FrogState.FROZEN: 150},
    FrogItemKey.CLASSY: {FrogState.NORMAL: 200, FrogState.FROZEN: 100},
}


def frog_exp(species_key: FrogItemKey, state: FrogState) -> int:
    """Seasonal exp granted by one unit of a species' item in ``state``."""
    return _SPECIES_EXP[species_key][state]


# item-owned consume statuses: the status class instances each item triggers.
# This is the item's composition, written as code (no payload objects).
_ITEM_STATUSES: dict[str, tuple[Status, ...]] = {
    "frog:pog:normal": (POG_REACTION,),
    "frog:pog:frozen": (POG_REACTION,),
    "frog:froggers:normal": (FROGGERS_REACTION,),
    "frog:froggers:frozen": (FROGGERS_REACTION,),
    "frog:classy:normal": (CLASSY_ROLE,),
    "frog:classy:frozen": (CLASSY_ROLE,),
}


def item_statuses(item_id: str) -> tuple[Status, ...]:
    """The statuses an frog item triggers on consume (the item's own)."""
    return _ITEM_STATUSES.get(item_id, ())


async def _consume_item(
    bot: "CazzuBot", uid: int, amount: int, item_id: str
) -> None:
    """The item-owned consume: exp, statuses, then the FrogConsumedEvent.

    The exp grant derives from the item's own id via ``frog_exp`` (the
    single oracle). The item's statuses are the classes it declares above;
    each ``apply`` to the member scope with the item id as provenance.
    The event stays last so domain observers see a *finished* consume.
    """
    _, species_str, state_str = item_id.split(":")
    species_key = FrogItemKey(species_str)
    state = FrogState(state_str)
    exp = frog_exp(species_key, state) * amount
    now = pendulum.now("UTC")

    await exp_db.add_exp_log(
        bot.db, uid, exp, now, source=MemberExpLogSourceEnum.FROG
    )

    for status in item_statuses(item_id):
        await status.apply(
            bot,
            scope=Scope.member(uid),
            provenance=item_id,
            now=now,
        )

    await bot.events.emit(
        FrogConsumedEvent(
            uid=uid,
            species_key=species_key,
            amount=amount,
            state=state,
            at=now.isoformat(),
        )
    )


async def _consume_basic_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for frog:basic:normal (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:basic:normal")


async def _consume_basic_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    await _consume_item(bot, uid, amount, "frog:basic:frozen")


async def _consume_pog_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    await _consume_item(bot, uid, amount, "frog:pog:normal")


async def _consume_pog_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    await _consume_item(bot, uid, amount, "frog:pog:frozen")


async def _consume_froggers_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    await _consume_item(bot, uid, amount, "frog:froggers:normal")


async def _consume_froggers_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    await _consume_item(bot, uid, amount, "frog:froggers:frozen")


async def _consume_classy_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    await _consume_item(bot, uid, amount, "frog:classy:normal")


async def _consume_classy_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    await _consume_item(bot, uid, amount, "frog:classy:frozen")


def _consume_blurb(species_key: FrogItemKey, state: FrogState) -> str:
    """The info card's "On consumption" — reads the same sources the glue
    uses (``frog_exp`` + the item's declared status classes), so display
    and grant cannot drift."""
    parts = [f"Grants **{frog_exp(species_key, state)}** seasonal exp."]
    for status in item_statuses(f"frog:{species_key.value}:{state.value}"):
        parts.append(status.describe())
    return " ".join(parts)


def _consumption_field(
    species_key: FrogItemKey, state: FrogState
) -> tuple[str, str]:
    return ("On consumption", _consume_blurb(species_key, state))


class FrogItems(Enum):
    """Every frog inventory item — basic/pog/froggers/classy × normal/frozen.

    Each entry is a bare ``Item`` literal: description prose + the
    consumption field derived from the oracle and the status classes.
    Frozen items reuse the normal-species art (D8). Cluster deliberately
    has no item — it can never be caught.
    """

    BASIC = Item(
        item_id="frog:basic:normal",
        display_name="Basic Frog",
        icon="🐸",
        description="The most normalest frog of them all.",
        icon_asset=FrogAsset.FROG_BASIC,
        consume=_consume_basic_normal,
        fields=(_consumption_field(FrogItemKey.BASIC, FrogState.NORMAL),),
    )
    BASIC_FROZEN = Item(...)  # as today (frog:basic:frozen)
    POG = Item(
        item_id="frog:pog:normal",
        display_name="Pog Frog",
        icon="🐸",
        description="A frog with a pog.",
        icon_asset=FrogAsset.FROG_POG,
        consume=_consume_pog_normal,
        fields=(_consumption_field(FrogItemKey.POG, FrogState.NORMAL),),
    )
    # ... POG_FROZEN, FROGGERS, FROGGERS_FROZEN, CLASSY, CLASSY_FROZEN as today
~~~~

The `FrogItems` enum body continues unchanged in shape (only consume glue +
fields change behind the same functions).

### Factory (`plugins/frogs/factory.py`) diffs

 -  Remove the `grant_catch_frog` + `_default_capture_embed` definitions
    (they moved to `behaviors.py`); keep `FrogCatchMenu`, `spawn_and_wait`,
    `on_frog_due`.
 -  The spawn dispatch:

~~~~ python
    species = by_key(species_key)
    if species is not None and species.spawn is not None:
        await species.spawn(
            bot,
            cid=cid,
            guild_id=bot.config.guild_id,
            persist=persist,
            now=pendulum.now("UTC"),
        )
        return False
~~~~

 -  The capture dispatch (inside `FrogCatchMenu.catch`):

~~~~ python
            if species.catch is not None:
                await species.catch(
                    self.bot,
                    uid=uid,
                    member=utils.member_snapshot(mctx.interaction.user),
                    species=species,
                    now=now,
                    cid=mctx.channel_id,
                )
                # (bookkeeping/event below unchanged)
~~~~

Note the capture **accounting** stays for every species regardless of
`catch`: `add_capture_log`, `modify_capture`, and the
`FrogCapturedEvent` are the flow's own ledger, not species behavior.
`species.catch is None` only means “no species behavior on capture”.

### `plugins/frogs/reactions.py` — pull by the class

Replace the payload-chance fold with a source→class→priority fold:

~~~~ python
# inside on_message (the existing guild_listener handler): the fold
# replaces the payload-chance read
from .statuses import status_by_source, ReactionStatus

async def on_message(event):
    ...
    contribs = await bot.statuses.list(Scope.member(uid), FrogSeam.FROG_REACTION)
    best = _best_reaction(contribs)
    if best is None:
        return
    chance = best.chance  # from the class, never the row
    if chance <= 0.0 or random.random() >= chance:
        return
    ... (cooldown + emoji + add_reaction unchanged)


def _best_reaction(contribs) -> ReactionStatus | None:
    """The highest-priority live reaction status (ties → lowest source key).

    Reads each contribution's ``source`` back to its registered class;
    unknown sources (a status removed from the registry) are skipped and
    eventually pruned at expiry.
    """
    statuses = [
        status_by_source(contrib.source)
        for contrib in contribs
    ]
    reaction = [s for s in statuses if isinstance(s, ReactionStatus)]
    if not reaction:
        return None
    return max(
        reaction,
        key=lambda s: (s.priority, s.key),
    )
~~~~

### Plugin loader (`plugins/frogs/__init__.py`) diffs

 -  Imports: drop `OutcomeKey`; import `ClusterBurst` from `behaviors` and
    `RoleConverger` + `classy_role_ids` from `statuses`.
 -  `on_load`:

~~~~ python
        # inject the cluster spawn implementation on the ClusterBurst
        # instance the species registry holds
        burst = by_key(FrogItemKey.CLUSTER)
        if burst is not None and isinstance(burst.spawn, ClusterBurst):
            burst.spawn.spawn_impl = factory.spawn_and_wait  # pyright: ignore
        self._bot = bot
        self._converger = RoleConverger(classy_role_ids())
        bot.statuses.register_converger(FrogSeam.CLASSY_ROLE, self._converger)
        ...
~~~~

 -  `on_unload` resets `burst.spawn.spawn_impl = None` (same guard).

### Deletions & the seams module

 -  Delete `plugins/frogs/outcomes.py` (the registry, hook stubs and
    payload dataclasses — the outcome library dissolves into the status
    classes in `plugins/frogs/statuses.py` and the species behaviors in
    `plugins/frogs/behaviors.py`).
 -  `plugins/frogs/seams.py`: drop `FrogStatus` (the identity enum); keep
    `FrogSeam` unchanged.
 -  `cazzubot/statuses.py` drop nothing; module docstring wording update
    (“instant catch/consume outcome library” → the status/behavior model).


Tech Stack
----------

Python 3.14, hikari 2.5, lightbulb 3.2, aiosqlite, pendulum; `dataclasses`
with `kw_only=True` on the new core `Status` + subclasses.


Baseline / Authority Refs
-------------------------

 -  `docs/CONTEXT.md` — canonical terms (status/outcome/seam). **Update** the
    outcome bullet: item composition is now **item-owned written glue over
    status classes**; the frog outcome library name is gone.
 -  `docs/FROG.md` — the concept requirements; the per-species rules inline
    (Pog 1%, Froggers 7%, Classy role/3h are all now **status-class values**).
    Optional wording pass after implementation.
 -  `docs/aegis/plans/2026-08-31-effects-to-statuses-outcomes.md` (D5/T8,
    decisions D1–D5) — parent plan; this plan executes the deferred D 5.
 -  `docs/needs-rewrite/STATUSES.md` (statuses seam store spec) phase-1/2
    records + `docs/needs-rewrite/DONE.md`.
 -  `cazzubot/statuses.py` — the seam/contribution/pull store (unchanged
    surface, plus the new `Status` class + registry).
 -  `tests/core/test_csr_boundary.py` — update `SERVICE_FILENAMES`
    (drop `outcomes.py`, keep `species.py`).


Compatibility Boundary
----------------------

 -  **No schema change; no migration.** The store table
    `status_contribution` (already renamed 007) and the converge tag stay.
    The `source` strings **change** semantics: from the shared identity
    `frog_reaction` payload rows to per-status keys (`frog:blessing:pog`,
    …). Pre-switch rows in the dev DB with the old source are orphans: the
    pull treats unknown sources as absent (skipped, lazily pruned on
    expiry) — no data rewrite needed for the short-lived reaction/role
    rows. Prod DB has no rows yet (006+007 deploy-pending).
 -  `bot.items.item_id`s, `frog_exp` oracle values and shapes, event types,
    `FrogItemKey`, `FrogState`, CLI, scheduler tags — all unchanged.
 -  The seam enum strings (`frog_reaction`, `classy_role`) stay. The
    classy role ids / embassy values move from items payloads into the
    status classes (already the same literals).
 -  **Known behavior change (intentional, per design)**: re-consume of the
    same or sibling status now writes the class's own row and EXTENDs only
    that row; the pull fold picks the highest-priority *live* class. Old
    “stronger overwrites while keeping the window additive” semantics are
    gone: consuming Froggers *while* a Pog row is live keeps both rows, the
    fold picks Froggers, and on Froggers expiry the pull falls back to the
    live Pog row — exactly the fallback behavior the backlog asked for.
    The visible reaction odds per moment are the same as before in the
    common cases; the difference only shows in the expiry-transition edges,
    which previously had no fallback at all.


TDD Route
---------

~~~~ text
TDD Route:
- Mode: off
- Decision: skipped
- Strict authority: not applicable (project has no strict-TDD request; existing
  suite (684 tests, green) is the regression net)
- Strict signals: n/a
- Light eligibility: n/a — existing tests updated + new focused unit tests
- Test posture: post-change regression + new unit coverage
- Reason: this is a large mechanical/design refactor of already-tested
  behavior (frogs); the suite + updated tests validate
- Verification: uv run pytest (full), ruff, basedpyright after each task
~~~~


Tasks
-----

> Each task is coherent + green before proceeding; one commit per task
> (unsigned per the host gotcha: `git -c commit.gpgsign=false commit`).
> Between tasks, hot-reload is not applied; run the suite only offline.

### Task 1 — Core `Status` class + registry (cazzubot/statuses.py)

**Files:**

 -  `cazzubot/statuses.py` (MODIFY — append the `Status` dataclass, registry
    functions, module docstring paragraph)
 -  `tests/core/test_statuses.py` (MODIFY — add class + registry tests)

**Why** statuses are core: any feature (item glue, species catch, a future
admin command) declares a status and invokes `apply()`. The store stops
owning values; the class does.

**Change necessity** — code change: the registry and the identity mapping
are new surfaces; values demanded by the design (see this doc).

**Steps**

1.  In `cazzubot/statuses.py` after the `ReapplyPolicy` enum add the
    `Status` dataclass (code above; keep the `kw_only=True` variants for
    the frog subclasses), the three-statement registry functions, and a
    docstring note that the module owns both the store and the status
    classes registry.

2.  In `tests/core/test_statuses.py`, add these tests:

    Add:
     -  `test_status_apply_publishes_provenance_only`
     -  `test_status_apply_rejects_wrong_scope_kind`
     -  `test_registry_roundtrip_by_source`
     -  `test_statuses_for_seam_filters_by_key`

    Complete code (paste into the test file):

    ~~~~ python
    @dataclass(frozen=True, slots=True, kw_only=True)
    class DummyStatus(Status):
        duty: int = 1


    SEAM_X = ...  # a tiny fake seam enum with .key/.external


    async def test_status_apply_publishes_provenance_only(full_bot):
        status = DummyStatus(
            key="k.1",
            name="x",
            seam=SEAM_X,
            duration=pendulum.duration(hours=1),
        )
        await status.apply(
            full_bot, scope=Scope.member(1), provenance="frog:pog:normal"
        )
        contribs = await full_bot.statuses.list(Scope.member(1), SEAM_X)
        assert contribs and contribs[0].payload == {"from": "frog:pog:normal"}
        assert contribs[0].source == "k.1"


    async def test_status_apply_enforces_scope_kind(full_bot):
        status = DummyStatus(
            key="k.2", seam=SEAM_X, scope_kind=ScopeKind.MEMBER
        )
        with pytest.raises(TypeError, match="member-scoped"):
            await status.apply(full_bot, scope=Scope.guild(2), provenance="p")


    def test_registry_by_source():
        register_status(s1)
        assert status_by_source("k") is s1
        assert status_by_source("none") is None
    ~~~~

    (Scaffold the fake seam exactly like `tests/core/test_statuses.py`
    current fake seams; reuse existing fixtures from that file.)

3.  Verification:

    ~~~~ sh
    uv run ruff check cazzubot/statuses.py tests/core/test_statuses.py
    uv run pytest tests/core/test_statuses.py
    uv run basedpyright
    ~~~~

    Commit:
    `git -c commit.gpgsign=false commit -am "feat(statuses): core Status class + registry (D5)"`

### Task 2 — Frog statuses module (plugins/frogs/statuses.py)

**Files:**

 -  `plugins/frogs/statuses.py` (NEW; full text in this doc above, with the
    missing bits filled: `_log` import, `TYPE_CHECKING` for `CazzuBot`,
    `SeamKey` extras, `StatusesClearedEvent` import if unused — drop)
 -  `plugins/frogs/seams.py` (MODIFY: delete `FrogStatus`)
 -  `plugins/frogs/__init__.py` (MODIFY: wiring, converger, cluster inject)

**Steps:**

1.  Write the file as shown (fill `_log` and the TYPE\_CHECKING import). Note
    `StatusesClearedEvent` is only used by the plugin's status editor — keep
    the import out unless the converger needs it (it does not).

2.  `seams.py`: remove the `FrogStatus` class (identity moved to
    `Status.key`); keep `FrogSeam`.

3.  `plugins/frogs/__init__.py` rewire as the diffs above.

4.  `tests/plugins/frogs/test_outcomes.py` is DELETED and superseded by
    `tests/plugins/frogs/test_statuses.py` (in Task 4) — do it in Task 4.

5.  Verification:

    ~~~~ sh
    uv run ruff check plugins/frogs/statuses.py plugins/frogs/seams.py plugins/frogs/__init__.py
    uv run pytest tests/plugins/frogs  -k "not outcomes"
    uv run basedpyright
    ~~~~

    Commit: `feat(frogs): unique status classes (values on the class)`

### Task 3 — Species compose behaviors (species.py + behaviors.py + factory)

**Files:**

 -  `plugins/frogs/behaviors.py` (new — `grant_catch` + `ClusterBurst`)
 -  `plugins/frogs/species.py` (rewrite — `catch`/`spawn` as `Behavior`,
    explicit grant for the four, Cluster burst)
 -  `plugins/frogs/factory.py` (diffs above: use `species.spawn` /
    `species.catch`; delete the moved helper defs)
 -  `plugins/frogs/extension.py` (catalog: `spawn` field name, still reads
    `frog_exp` for the consume line)

**Steps:**

1.  Move the existing `grant_catch_frog` + `_default_capture_embed` (and
    their `templates`/`utils`/`formatter` helpers) verbatim from
    `factory.py` into `behaviors.py`, **renaming `grant_catch_frog` →
    `grant_catch`**, plus add the `ClusterBurst` class.
     -  `behaviors.py` must not import `factory` or `species` at runtime —
        `species` only in `TYPE_CHECKING` + it is passed as an argument.

2.  Rewrite `species.py` to the shape above (fields `catch`/`spawn`).

3.  Update `factory.py` per the diffs. (Also `from .behaviors import` not
    needed — the species already carries the behavior; factory calls via
    the species.)

4.  Update `extension.py` line 113: `species.spawn_outcome` →
    `species.spawn is not None`. The ‘cannot be caught’ branch stays for
    a spawn-owning species; the consumed line unchanged.

5.  Tests to update in `tests/plugins/frogs/test_species.py` —
     -  `test_species_registry_has_frogmd_five` keeps weights; change
        `cluster.spawn_outcome is not None` → `cluster.spawn is not None`,
        and add `cluster.catch is None`.

     -  `test_default_capture_grants_item(bot: full_bot…)` replaces the old
        dispatcher test: a fake species `catch=grant_catch` grants the item:

        ~~~~ python
        async def test_species_grant_catch_adds_item(full_bot):
            from plugins.frogs.behaviors import grant_catch

            species = by_key(FrogItemKey.POG)
            member = utils.member_snapshot(FakeMember(id=123, name="t"))
            await grant_catch(
                full_bot,
                uid=123,
                member=member,
                species=species,
                now=pendulum.now("UTC"),
                cid=99,
            )
            assert await full_bot.inventory.get(123, "frog:pog:normal") == 1
        ~~~~

     -  New: `test_catch_none_grants_nothing` — a synthetic species with
        `catch=None` → nothing added.

6.  Verification:

    ~~~~ sh
    uv run pytest tests/plugins/frogs/test_species.py tests/plugins/frogs/test_extension.py tests/plugins/frogs/test_cadences.py
    uv run basedpyright
    ~~~~

    Commit: `feat(frogs): species compose behaviors (catch/spawn as code)`

### Task 4 — reactions pull + status tests (the fold referee)

**Files:**

 -  `plugins/frogs/reactions.py` (MODIFY — `_best_reaction` fold, see above)
 -  `tests/plugins/frogs/test_reactions.py` (MODIFY — the fold/fallback cases)
 -  `tests/plugins/frogs/test_statuses.py` (new — replaces test\_outcomes.py)

**Steps:**

1.  Rewrite the fold as shown. Keep the cooldown/throttle/emoji logic byte-
    identical. Removed the “one row by construction” comment.

2.  `test_statuses.py`:
     -  Status describes + apply-providence (Pog + Froggers as **separate**
        rows — the sibling case):

        ~~~~ python
        async def test_reaction_statuses_are_separate_rows(full_bot):
            now = pendulum.now("UTC")
            await POG_REACTION.apply(
                full_bot,
                scope=Scope.member(1),
                provenance="frog:pog:normal",
                now=now,
            )
            await FROGGERS_REACTION.apply(
                full_bot,
                scope=Scope.member(1),
                provenance="frog:froggers:normal",
                now=now,
            )
            rows = await full_bot.statuses.list(
                Scope.member(1), FrogSeam.FROG_REACTION, now=now
            )
            assert {r.source for r in rows} == {
                "frog:blessing:pog",
                "frog:blessing:froggers",
            }
        ~~~~

     -  fallback: expire the Froggers row (list at `now+1h+ε`), then the fold
        returns Pog:

        ~~~~ python
        def test_fold_picks_highest_priority():
            # build the two with sources; assert (FROGGERS, FROGGERS_REACTION) wins; simulate
            # only-Pog → POG wins; unknown sources skipped
        ~~~~

     -  `test_classy_role_apply_publishes_and_converges` (replaces the old
        role converge test — converger from the module).

     -  `test_exp_vestige_deleted`: ExpOutcome/ExpPayload imports are removed
        wholesale — the old exp *outcome* tests are deleted; exp grant is
        covered by items tests (Task 5).

     -  Delete `tests/plugins/frogs/test_outcomes.py`.

3.  Verification:

    ~~~~ sh
    uv run pytest tests/plugins/frogs/test_statuses.py tests/plugins/frogs/test_reactions.py
    uv run ruff check .
    ~~~~

    Commit: `test(frogs): status folds by priority; delete outcome machinery`

### Task 5 — items compose statuses + info card

**Files:**

 -  `plugins/frogs/items.py` (rewrite above)
 -  `tests/plugins/frogs/test_items.py` (MODIFY)
 -  `tests/plugins/frogs/test_extension.py` (catalog — unchanged exp lines)

**Steps:**

1.  Replace `items.py` per the layout above (the `FrogItems` enum's ids,
    display names and art stay byte-identical; swap the `consume=` glue
    and `fields=` values to the item-statuses model).

2.  Update `test_items.py`:
     -  Drop imports of `_SPECIES_OUTCOMES`, `ExpPayload`, `OutcomeKey`.

     -  `test_consume_blurb_describes_composed_outcomes`: now the blurb text
        comes from the status classes' describe — update the expected strings:

        ~~~~ python
        assert (
            _consume_blurb(FrogItemKey.POG, FrogState.NORMAL)
            == "Grants **30** seasonal exp. For 1 hour, a **1%** chance ..."
        )  # per describe()
        ~~~~

     -  New: `test_item_composes_only_its_statuses` (pog → reaction row only).

     -  New: `test_provenance_is_item_id`.

     -  Keep `test_consume_composes_item_outcomes` but address `chance` read
        from the class:
        `assert isinstance(status_by_source(contrib.source), ReactionStatus)` …
        `describe`.

3.  Verification:

    ~~~~ sh
    uv run pytest tests/plugins/frogs/test_items.py tests/integration
    uv run ruff format --check plugins/frogs/items.py  # or format first
    ~~~~

    Commit: `refactor(frogs): items consume glue composes status classes`

### Task 6 — delete the old machinery + boundary sweep

**Files:**

 -  `plugins/frogs/outcomes.py` (DELETE)
 -  `cazzubot/statuses.py` (docstring touch — paragraph references to the
    outcome library → the status/behavior model)
 -  `tests/core/test_csr_boundary.py`: `SERVICE_MODULES` — drop
    “outcomes.py” (already deleted); keep species.py (stays hikari-free).
 -  Grep sweeps for stale names:
    `grep -rIn 'OutcomeKey\|ExpPayload\|_SPECIES_OUTCOMES\|catch_outcome\|spawn_outcome\|FrogStatus' plugins/ tests/ cazzubot/`
    → expect only historical docs + this plan.

**Verification:**

~~~~ sh
uv run ruff check . && uv run ruff format --check .
uv run basedpyright
uv run pytest   # full suite
~~~~

Commit: `refactor(frogs): delete outcome registry/payload machinery`

### Task 7 — docs + backlog

**Files:**

 -  `docs/CONTEXT.md` — (update the **outcome** bullet): items compose
    their **statuses by code**; status invokes store; species compose
    behaviors; no more “frog outcome library” name; remove the “backlog
    item” parenthetical; add “behavior” (= code a species/item composes).
 -  `docs/needs-rewrite/STATUSES.md` — phase 1/2 records: replace the
    “OutcomeKey library”, “ExpOutcome fossil” paras with the new model:
    status classes own values; the fold in the feature pulls; per-status
    policy; the items compose statuses; **no schema change**.
 -  `docs/how-do-i/add-a-frog-species.md` — catch behavior is now code
    (`catch=grant_catch` / custom function), mention `plugins/frogs/statuses.py`
    for status effects; items' composition to status classes.
 -  `docs/needs-rewrite/BACKLOG.md` — the entry the backlog item this plan
    implements; move a **Done** note to `docs/needs-rewrite/DONE.md`
    (per the repo convention: completed backlog items are archived there
    with a brief “how resolved” line).
 -  `docs/FROG.md` (optional light pass, concept only): the per-species
    “On Consumption” bullets keep the plain requirements prose; revisit
    only if a contradiction with the new model shows up.

**Verification:** read-through + `grep -rn 'catch_effect\|spawn_effect' docs/`
(expect none live).

Commit: `docs(frogs): statuses own values; species compose behaviors docs`


Risks & Retirement
------------------

 -  **Behavior change vs old strongest-wins**: the pull fold is priority-first;
    both rows exist. Covered by tests + this doc's Compatibility Boundary.
 -  **Unknown source rows**: old `frog_reaction`/`classy_role` rows (dev DB)
    become orphaned and are skipped by the fold; lazy expiry prunes them.
    No migration.
 -  **CSR boundary**: `species.py` must NOT import hikari (it imports only
    the behaviors *values* from `behaviors.py`; that module imports hikari,
    fine — it is controller-shaped like factory).
    `tests/core/test_csr_boundary.py` keeps `species.py` in the enforced list;
    `outcomes.py` removed by deletion.
 -  **Rollback**: revert the commits; the old `outcomes.py` returns via git —
    no data migration means old code boots against the same schema.
 -  **Retired**: `plugins/frogs/outcomes.py`, `FrogStatus`, the
    `_SPECIES_OUTCOMES` dict, `ExpOutcome`/`ExpPayload`,
    ReactionOutcome/Role/Burst-with-payload classes, info-card payload
    reading. None are external.


Execution Readiness View
------------------------

~~~~ text
Execution Readiness View:
- Intent Lock: species compose behavior as code (catch/spawn callables);
  items compose status classes by glue; status values on class; seam fold
  maps source→class→priority; fallback on expiry by the store itself
- Scope Fence: no schema/migration; no changes to items oracle/events/
  seam enum key strings; no engine rule for siblings; EXP stays item-
  owned; prod untouched; docs term updates only
- Baseline Lock: doc plans are authoring/history (parent 2026-08-31
  remains valid); CONTEXT.md canonical terms refreshed
- Approved Behavior: full suite green after each Task; no new pinned odds
  drift (Pog 1% / Froggers 7% / Classy 3h keep value placement on class
  — statuses own those numbers)
- Owner / Contract Constraints: bot.statuses owns the store; status
  classes own values; species compose catch/spawn; items compose their
  statuses; the events bus owns observers
- Compatibility Boundary: stored table + tags + item_id + oracle
  unchanged; contributions use new source strings (orphan-safe)
- Retirement Boundary: outcomes.py gone after Task 3; old payload/registry
  names gone from comments/docs except history
- Task Batches: T1 core, T2 frog statuses, T3 species, T4 reactions fold,
  T5 items, T6 cleanup + full suite, T7 docs
- Test Obligations: focused per task + full suite end
- Review Gates: this plan reviewed (user) before execution; commit per
  Task
- Drift / Rewind Rules: on suite failure in a Task, fix that branch before
  continuing; the parent plan's drift gates apply
- Evidence Required Before Completion: full suite green; grep shows no live
  Outcome/Payload registry names; docs updated
- Advisory Boundary: method-pack execution guidance only; not approvals
~~~~


Execution Route
---------------

~~~~ text
Execution Route:
- Decision: inline (sequential; tasks touch overlapping files —
  species.py/items.py/factory.py; no parallel subagent value)
- Evidence: cross-cutting refactor; each task compiles & green before
  next; coordinator driver review
- Fallback: revert individual commits (no data migration)
- User confirmation required: no — approved backlog turn + this plan review
~~~~
