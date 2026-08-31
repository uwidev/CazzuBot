"""Frog species outcomes — a typed, payload-driven outcome library.

Outcomes are the species-side counterpart of item outcomes: *what a
thing does* (on catch, on consume, on spawn). They are fully decoupled
from the species and the controllers:

- Each outcome owns a **payload dataclass** — its configuration. A
  species definition carries payload *instances* (``catch_outcome``), so
  one outcome class is reusable with different values, and a species
  never carries fields for outcomes it doesn't use.
- A payload's ``key`` is an :class:`OutcomeKey` enum member, and **the
  enum IS the registry**: each member's value is its handler object.
  ``payload.key.value`` is the outcome with its ``catch``/``consume``
  hooks — dispatch is a plain attribute access, no lookup table, so a key
  without a handler cannot exist (the LSP guarantee is structural, not a
  test).
- Hooks receive the **bot** plus the payload; consume hooks take a
  **Scope** — outcomes modify state for any target, they never decide
  what consumption does.

The status/outcome boundary (2026-08-31): a **status** is persistent,
scope-aware state recorded by the status store (``cazzubot/statuses.py``,
``bot.statuses``); an **outcome** is the consequence of an action and may
*invoke statuses* through the store — never the reverse.

No hikari imports: ``bot`` is only a parameter (TYPE_CHECKING-annotated);
outcomes reach services through it.

Consume outcomes are **generic, scope-aware primitives** (owner
2026-08-28): each takes a :class:`~cazzubot.statuses.Scope` plus the
granting item id as ``provenance``, so *any* caller — the item's consume
composition today (``items.py::_SPECIES_OUTCOMES``), an admin command
tomorrow — can apply them to any member/guild. ``REACTION``/``ROLE`` are
the first such outcomes (they publish statuses); ``EXP`` is the
pre-composition fossil (exp grant is item-owned behavior, so it is
composed into nothing and slated for removal). The cluster spawn hook
lives in this same module with its factory dependency injected at load —
nothing here imports the factory.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, cast

import pendulum

from cazzubot.statuses import ReapplyPolicy, Scope, ScopeKind
from cazzubot.models import FrogState, MemberExpLogSourceEnum, FrogItemKey

from plugins.experience import db as exp_db

from .seams import FrogStatus, FrogSeam

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)

# hikari-free channel-type check: hikari.ChannelType.GUILD_TEXT == 0 and
# the REST returns channel objects whose ``type`` is that value.
_GUILD_TEXT = 0


def frog_item_key(species_key: FrogItemKey, state: FrogState) -> str:
    """The inventory item string for a species in a state (one derivation).

    Mirrors ``db.FrogItem.key``, which delegates here, so a consume
    outcome's status ``source`` is byte-identical to the consumed
    item id.
    """
    return f"frog:{species_key.value}:{state.value}"


class OutcomePayload(Protocol):
    """A species-side outcome configuration.

    Any dataclass whose ``key`` is an :class:`OutcomeKey` member; the key
    selects the outcome that consumes the payload. Protocol status means
    a species' outcome fields can only hold objects with a valid key —
    never a bare string.
    """

    key: OutcomeKey


class Outcome(Protocol):
    """One species outcome: optional catch hook, optional consume hook.

    The catch hook receives the bot, the species' payload instance for
    this outcome, and the entity context (uid / species key / now). The
    consume hook is a **generic modifier**: the bot, the payload, and a
    Scope with the granting item id as ``provenance`` (+ amount / now).
    Unused hooks are no-ops; a species with no outcome on a side leaves
    that side None.
    """

    async def catch(
        self,
        bot: "CazzuBot",
        payload: OutcomePayload,
        *,
        uid: int,
        species_key: FrogItemKey,
        now: pendulum.DateTime,
    ) -> None:
        """Handle the outcome's catch side (a protocol contract; each
        outcome implements it)."""
        ...

    async def consume(
        self,
        bot: "CazzuBot",
        payload: OutcomePayload,
        *,
        scope: Scope,
        provenance: str,
        amount: int,
        now: pendulum.DateTime,
    ) -> None:
        """Handle the outcome's consume side (a protocol contract; each
        outcome implements it).

        A modifier takes a **Scope** (member or guild) plus the granting
        item id as ``provenance`` — it never decides *what consumption
        does*; callers (item composition, an admin command) compose it.
        """
        ...


class ExpOutcome:
    """``exp`` — consume outcome: seasonal exp per payload (a fossil)."""

    async def catch(
        self,
        bot: "CazzuBot",
        payload: OutcomePayload,
        *,
        uid: int,
        species_key: FrogItemKey,
        now: pendulum.DateTime,
    ) -> None:
        """No catch behavior — exp is granted on consume only."""
        return None  # no catch behavior

    async def consume(
        self,
        bot: "CazzuBot",
        payload: OutcomePayload,
        *,
        scope: Scope,
        provenance: str,
        amount: int,
        now: pendulum.DateTime,
    ) -> None:
        """Grant the payload's per-unit exp to the scope's member.

        Fossil (owner 2026-08-28): consume-side exp is **item-owned**
        behavior — the item grants its own exp from the ``frog_exp``
        oracle in ``items.py`` — so this hook is composed into nothing
        and exists only because :data:`OutcomeKey.EXP` predates the
        composition split. It grants the normal per-unit value (the
        frozen concept belongs to the item, not the modifier) and is
        slated for removal (see docs/needs-rewrite/STATUSES.md).
        """
        if not isinstance(payload, ExpPayload):
            raise TypeError(
                "exp outcome requires ExpPayload, got "
                f"{type(payload).__name__}"
            )
        if scope.kind is not ScopeKind.MEMBER:
            raise TypeError(
                "exp grants are member-scoped, got "
                f"{scope.kind.value} scope"
            )
        await exp_db.add_exp_log(
            bot.db,
            scope.id,
            payload.exp * amount,
            now,
            source=MemberExpLogSourceEnum.FROG,
        )


class ReactionOutcome:
    """``reaction`` — a generic, composable outcome: publish/merge the
    ONE reaction status for a Scope.

    Outcomes invoke statuses (2026-08-31): this one publishes the
    reaction-chance status. Generic by design (owner 2026-08-28): takes
    a **Scope**, so item composition applies it to the consuming member
    today, and a future admin command can apply it to any member/guild.
    Pog and Froggers are the same status: both publish to the single
    ``(scope, seam, source)`` row under the shared status identity
    ``FrogStatus.REACTION`` — never per-item sources — and the granting
    item travels in the payload as ``"from"`` provenance.

    While the window is active: the **strongest** chance wins (a
    Froggers overwrites a live Pog's 1% with 7%) and **every** consume
    extends the window additively (old ``expires_at`` plus its hour —
    FROG.md's "duration only, never stronger" spirit); after expiry a
    fresh consume starts anew. The value comparison is feature-side —
    the store never interprets payloads — so this hook fetches, compares
    and picks the write: REPLACE (new value + remaining rolling window)
    when strictly stronger, EXTEND (keep value, roll) otherwise.
    """

    async def catch(
        self,
        bot: "CazzuBot",
        payload: OutcomePayload,
        *,
        uid: int,
        species_key: FrogItemKey,
        now: pendulum.DateTime,
    ) -> None:
        """No catch behavior — the outcome applies on consume only."""
        return None

    async def consume(
        self,
        bot: "CazzuBot",
        payload: OutcomePayload,
        *,
        scope: Scope,
        provenance: str,
        amount: int,
        now: pendulum.DateTime,
    ) -> None:
        """Publish/merge the shared reaction status into ``scope``."""
        if not isinstance(payload, ReactionPayload):
            raise TypeError(
                "reaction outcome requires ReactionPayload, got "
                f"{type(payload).__name__}"
            )
        seam = FrogSeam.FROG_REACTION
        source = FrogStatus.REACTION.key
        prov: dict[str, object] = {
            "chance": payload.chance,
            "from": provenance,
        }
        existing = await bot.statuses.fetch(scope, seam, source, now=now)
        current = 0.0
        if existing is not None:
            value = existing.payload.get("chance", 0.0)
            if isinstance(value, (int, float)):
                current = float(value)
        if existing is None or payload.chance > current:
            # fresh, or strictly stronger: write the new value while
            # keeping the remaining window additive (REPLACE sets
            # expires_at = now + duration, so hand it remaining+duration)
            remaining = (
                (existing.expires_at - now)
                if existing is not None and existing.expires_at is not None
                else pendulum.duration()
            )
            await bot.statuses.publish(
                scope,
                seam,
                source,
                prov,
                duration=remaining + payload.duration,
                policy=ReapplyPolicy.REPLACE,
                now=now,
            )
        else:
            # weaker/equal: keep the value, extend the window additively
            await bot.statuses.publish(
                scope,
                seam,
                source,
                prov,
                duration=payload.duration,
                policy=ReapplyPolicy.EXTEND,
                now=now,
            )


class RoleOutcome:
    """``role`` — a generic, composable outcome: publish the one classy-
    role status for a Scope.

    Outcomes invoke statuses (2026-08-31): this one publishes the
    classy-role status. ``FrogSeam.CLASSY_ROLE`` is an external seam:
    ``Statuses.publish`` runs the RoleConverger synchronously (role
    added now) and schedules the converge job at expiry (role removed
    then); explicit clear reverts instantly via StatusesClearedEvent.
    Normal and frozen Classy are the same status (one row, EXTEND rolls
    the duration); the
    guild-side role id is resolved here from ``bot.config.guild_kind`` so
    the stored payload is the concrete role the converger must converge
    to, with the granting item as provenance. Scope-aware like every
    modifier — item composition passes the member scope; a future admin
    command could target any member.
    """

    async def catch(
        self,
        bot: "CazzuBot",
        payload: OutcomePayload,
        *,
        uid: int,
        species_key: FrogItemKey,
        now: pendulum.DateTime,
    ) -> None:
        """No catch behavior — the outcome applies on consume only."""
        return None

    async def consume(
        self,
        bot: "CazzuBot",
        payload: OutcomePayload,
        *,
        scope: Scope,
        provenance: str,
        amount: int,
        now: pendulum.DateTime,
    ) -> None:
        """Publish the role grant into ``scope``."""
        if not isinstance(payload, RolePayload):
            raise TypeError(
                "role outcome requires RolePayload, got "
                f"{type(payload).__name__}"
            )
        role_id = payload.role_id_for(bot.config.guild_kind)
        await bot.statuses.publish(
            scope,
            FrogSeam.CLASSY_ROLE,
            source=FrogStatus.CLASSY_ROLE.key,
            payload={"role_id": role_id, "from": provenance},
            duration=payload.duration,
            policy=ReapplyPolicy.EXTEND,
            now=now,
        )


class RoleConverger:
    """World-reconciliation for the CLASSY_ROLE seam (member roles).

    Registered via ``bot.statuses.register_converger`` at plugin load
    (Phase 2 wiring — Phase 1 ships this tested but unwired). Idempotent
    by construction: reads the seam's active contributions, computes the
    wanted role set, then diffs against the member's actual roles —
    adding missing, removing only roles this seam could grant (the bound
    ``role_ids``) that are no longer wanted. A member who left the guild
    fails fetch_member: logged and returned — the scheduler's converge
    job retries with backoff until the row expires/clears.
    """

    def __init__(self, role_ids: frozenset[int]) -> None:
        """Bind the role ids this seam may grant.

        Derived from the species registry's payloads by
        ``plugins/frogs/__init__.py`` (which imports both ``species`` and
        ``outcomes``, so ``outcomes`` never imports ``species`` — the
        edge ``species → outcomes`` stays one-way).
        """
        self._known = role_ids

    def _known_role_ids(self) -> frozenset[int]:
        """Every role id this seam is allowed to remove."""
        return self._known

    async def __call__(
        self, bot: "CazzuBot", scope: Scope, seam: str
    ) -> None:
        """Reconcile one member's classy roles to the active contributions."""
        if scope.kind is not ScopeKind.MEMBER:
            return
        contribs = await bot.statuses.list(scope, FrogSeam.CLASSY_ROLE)
        wanted: set[int] = set()
        for contrib in contribs:
            role_id = contrib.payload.get("role_id")
            if isinstance(role_id, int):
                wanted.add(role_id)
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
        for role_id in (current & self._known_role_ids()) - wanted:
            await bot.rest.remove_role_from_member(
                bot.config.guild_id, scope.id, role_id, reason=reason
            )


class ClusterOutcome:
    """``cluster`` — the spawn outcome: burst child frogs into nearby
    channels.

    An *outcome*, not a status (2026-08-31): it is not persistent
    scope-aware state — it is the consequence of a spawn reaching a
    cluster frog. Children are spawned through ``spawn_impl`` — the
    factory's ``spawn_and_wait`` — which this module cannot import (the
    edge ``outcomes → factory`` would cycle through species). The
    plugin's ``on_load`` injects it (see plugins/frogs/__init__.py),
    keeping the import graph acyclic and hikari out of this service
    module. Children run as **tracked background tasks** so the scheduler
    handler returns immediately instead of blocking on up to 10 capture
    waits.
    """

    def __init__(self) -> None:
        """Bind the per-instance spawn implementation.

        A class attribute holding a plain function would **bind** on
        instance access (the registered handler would receive this
        ClusterOutcome as its first argument), so the injection lives on
        the instance. The registry singleton (``OutcomeKey.CLUSTER.value``
        — the one the spawn dispatch always uses) gets it from the
        plugin's ``on_load``; tests inject their own on fresh instances.
        """
        self.spawn_impl: Callable[..., Awaitable[bool]] | None = None
        # strong references keep background child tasks alive until done
        self._background: set[asyncio.Task[Any]] = set()

    async def catch(
        self,
        bot: "CazzuBot",
        payload: OutcomePayload,
        *,
        uid: int,
        species_key: FrogItemKey,
        now: pendulum.DateTime,
    ) -> None:
        """No catch behavior — a cluster frog can never be captured."""
        return None

    async def consume(
        self,
        bot: "CazzuBot",
        payload: OutcomePayload,
        *,
        scope: Scope,
        provenance: str,
        amount: int,
        now: pendulum.DateTime,
    ) -> None:
        """No consume behavior — cluster has no item (uncatchable)."""
        return None

    async def spawn(
        self,
        bot: "CazzuBot",
        payload: OutcomePayload,
        *,
        cid: int,
        guild_id: int,
        persist: int,
        now: pendulum.DateTime,
    ) -> None:
        """Explode: 4–10 child Basic frogs into the text channels around ``cid``."""
        if not isinstance(payload, ClusterPayload):
            raise TypeError(
                "cluster outcome requires ClusterPayload, got "
                f"{type(payload).__name__}"
            )
        if self.spawn_impl is None:
            _log.error(
                "cluster outcome has no spawn_impl — plugin on_load missed"
            )
            return
        zone = await self._zone(bot, guild_id, cid, payload.radius)
        if not zone:
            _log.warning(
                "cluster spawn channel %s outside text channels", cid
            )
            return
        count = random.randint(payload.min_spawns, payload.max_spawns)
        targets = [random.choice(zone) for _ in range(count)]
        _log.info(
            "cluster frog bursts %d basic(s) across %d channel(s)",
            count,
            len(zone),
        )
        for target in targets:
            self._start_child(bot, payload, persist, target)
            if payload.delay > 0:
                await asyncio.sleep(payload.delay)

    async def _zone(
        self, bot: "CazzuBot", guild_id: int, cid: int, radius: int
    ) -> list[tuple[int, int]]:
        """(channel_id, position) pairs within ``radius`` of ``cid``.

        Text channels only, ordered by (position, id); the zone is the
        slice ±``radius`` around the spawn channel, clamped at both ends.
        """
        channels = await bot.rest.fetch_guild_channels(guild_id)
        texts = [
            (
                int(channel.id),
                int(getattr(channel, "position", 0) or 0),
            )
            for channel in channels
            if getattr(channel, "type", None) == _GUILD_TEXT
        ]
        texts.sort(key=lambda entry: (entry[1], entry[0]))
        ids = [entry[0] for entry in texts]
        if cid not in ids:
            return []
        index = ids.index(cid)
        return texts[max(0, index - radius) : index + radius + 1]

    def _start_child(
        self,
        bot: "CazzuBot",
        payload: "ClusterPayload",
        persist: int,
        target: tuple[int, int],
    ) -> None:
        """Fire one child Basic-frog spawn as a tracked background task."""
        impl = self.spawn_impl
        if impl is None:
            _log.error(
                "cluster outcome has no spawn_impl — plugin on_load missed"
            )
            return
        child_persist = persist or payload.persist
        task = asyncio.create_task(
            cast(
                Coroutine[Any, Any, bool],
                impl(
                    bot,
                    child_persist,
                    cid=target[0],
                    species_key=payload.child_species,
                ),
            )
        )
        self._background.add(task)
        task.add_done_callback(self._background.discard)


class OutcomeKey(Enum):
    """The outcome library — each member's value IS its handler.

    ``EXP`` is the pre-composition fossil: consume-side exp is item-owned
    behavior (the oracle in ``items.py``), so it is composed into nothing
    and slated for removal. ``REACTION``/``ROLE`` are generic, scope-aware
    consume outcomes (2026-08-28 separation) that publish statuses: any
    caller — item composition today, an admin command tomorrow — applies
    them to any member/guild scope. ``CLUSTER`` is the spawn-side outcome
    (its ``spawn`` replaces the catchable frog at spawn time). Adding an
    outcome = define the handler class, then one enum member; dispatch
    everywhere is ``payload.key.value`` and needs no registration or
    lookup.
    """

    EXP = ExpOutcome()
    REACTION = ReactionOutcome()
    ROLE = RoleOutcome()
    CLUSTER = ClusterOutcome()


@dataclass(frozen=True, slots=True)
class ExpPayload:
    """The ``exp`` consume outcome's configuration (a fossil).

    ``exp`` is the value per frog in the normal state, ``frozen_exp`` the
    value when consumed frozen (the default species preserves the legacy
    10/3). Slated for removal with :class:`ExpOutcome`: live consume-exp
    values live in the item oracle (``items.py::frog_exp``) — this
    payload predates the item-owned composition split.
    """

    key = OutcomeKey.EXP

    exp: int
    frozen_exp: int

    def per_frog(self, state: FrogState) -> int:
        """Exp granted per frog consumed in ``state``."""
        return self.frozen_exp if state is FrogState.FROZEN else self.exp

    def total(self, state: FrogState, amount: int) -> int:
        """Total exp for consuming ``amount`` frogs in ``state``."""
        return self.per_frog(state) * amount


@dataclass(frozen=True, slots=True)
class ReactionPayload:
    """The ``reaction`` consume outcome's configuration.

    ``chance`` is the strongest-wins value merged into the shared
    frog-reaction seam row; ``duration`` is the additive window rolled
    on every consume (FROG.md: "only the duration is increased, never a
    stronger outcome").
    """

    key = OutcomeKey.REACTION

    chance: float
    duration: timedelta


@dataclass(frozen=True, slots=True)
class RolePayload:
    """The ``role`` consume outcome's configuration — the classy role.

    FROG.md's two role ids, one per guild side; ``duration`` is the
    grant's lifetime (EXTEND rolls it on re-consume).
    """

    key = OutcomeKey.ROLE

    role_dev: int
    role_prod: int
    duration: timedelta

    def role_id_for(self, guild_kind: str) -> int:
        """The concrete role id for the guild side (FROG.md's two ids)."""
        return (
            self.role_dev
            if guild_kind == "development"
            else self.role_prod
        )


@dataclass(frozen=True, slots=True)
class ClusterPayload:
    """The ``cluster`` spawn outcome's configuration (FROG.md defaults).

    Replaces the catchable frog at spawn time (``Species.spawn_outcome``):
    burst ``min_spawns``..``max_spawns`` child frogs into the text
    channels within ``radius`` of the spawn channel, staggered by
    ``delay`` seconds (the rate-limit guard).
    """

    key = OutcomeKey.CLUSTER

    min_spawns: int = 4
    max_spawns: int = 10
    radius: int = 2  # text channels up AND down from the spawn channel
    delay: float = 0.75  # seconds between child spawns (rate-limit guard)
    child_species: FrogItemKey = FrogItemKey.BASIC
    persist: int = 30  # child lifetime when the spawning ctx omits persist
