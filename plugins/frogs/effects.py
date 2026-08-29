"""Frog species effects — a typed, payload-driven effect registry.

Effects are fully decoupled from the species and the controllers:

- Each effect owns a **payload dataclass** — its configuration. A species
  definition carries payload *instances* (``catch_effect``), so one
  effect class is reusable with different values, and a species never
  carries fields for effects it doesn't use.
- A payload's ``key`` is an :class:`EffectKey` enum member, and **the
  enum IS the registry**: each member's value is its handler object.
  ``payload.key.value`` is the effect with its ``catch``/``consume``
  hooks — dispatch is a plain attribute access, no lookup table, so a key
  without a handler cannot exist (the LSP guarantee is structural, not a
  test).
- Hooks receive the **bot** plus the payload; consume hooks take a
  **Scope** — effects modify state for any target, they never decide
  what consumption does.

No hikari imports: ``bot`` is only a parameter (TYPE_CHECKING-annotated);
effects reach services through it.

Consume modifiers are **generic, scope-aware primitives** (owner
2026-08-28): each takes a :class:`~cazzubot.effects.Scope` plus the
granting item id as ``provenance``, so *any* caller — the item's consume
composition today (``items.py::_SPECIES_CONSUME``), an admin command
tomorrow — can apply them to any member/guild. ``REACTION``/``ROLE`` are
the first such modifiers; ``EXP`` is the pre-composition fossil (exp
grant is item-owned behavior, so it is composed into nothing and slated
for removal). Phase 2 of the frog-species plan adds the spawn-side
Cluster hook in this same module with its factory dependency injected at
load — nothing here imports the factory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING, Protocol

import pendulum

from cazzubot.effects import ReapplyPolicy, Scope, ScopeKind
from cazzubot.models import FrogState, MemberExpLogSourceEnum, FrogItemKey

from plugins.experience import db as exp_db

from .seams import FrogEffect, FrogSeam

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)


def frog_item_key(species_key: FrogItemKey, state: FrogState) -> str:
    """The inventory item string for a species in a state (one derivation).

    Mirrors ``db.FrogItem.key``, which delegates here, so a consume
    effect's seam ``source`` is byte-identical to the consumed item id.
    """
    return f"frog:{species_key.value}:{state.value}"


class EffectPayload(Protocol):
    """A species-side effect configuration.

    Any dataclass whose ``key`` is an :class:`EffectKey` member; the key
    selects the effect that consumes the payload. Protocol status means a
    species' effect fields can only hold objects with a valid key — never
    a bare string.
    """

    key: EffectKey


class Effect(Protocol):
    """One species effect: optional catch hook, optional consume hook.

    The catch hook receives the bot, the species' payload instance for
    this effect, and the entity context (uid / species key / now). The
    consume hook is a **generic modifier**: the bot, the payload, and a
    Scope with the granting item id as ``provenance`` (+ amount / now).
    Unused hooks are no-ops; a species with no effect on a side leaves
    that side None.
    """

    async def catch(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        uid: int,
        species_key: FrogItemKey,
        now: pendulum.DateTime,
    ) -> None:
        """Handle the effect's catch side (a protocol contract; each effect
        implements it)."""
        ...

    async def consume(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        scope: Scope,
        provenance: str,
        amount: int,
        now: pendulum.DateTime,
    ) -> None:
        """Handle the effect's consume side (a protocol contract; each
        effect implements it).

        A modifier takes a **Scope** (member or guild) plus the granting
        item id as ``provenance`` — it never decides *what consumption
        does*; callers (item composition, an admin command) compose it.
        """
        ...


class ExpEffect:
    """``exp`` — consume: seasonal exp per payload values (a fossil)."""

    async def catch(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
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
        payload: EffectPayload,
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
        and exists only because :data:`EffectKey.EXP` predates the
        composition split. It grants the normal per-unit value (the
        frozen concept belongs to the item, not the modifier) and is
        slated for removal (see docs/needs-rewrite/EFFECTS.md).
        """
        if not isinstance(payload, ExpPayload):
            raise TypeError(
                "exp effect requires ExpPayload, got "
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


class ReactionEffect:
    """``reaction`` — a generic, composable state modifier: publish/merge
    the ONE reaction effect for a Scope.

    Generic by design (owner 2026-08-28): takes a **Scope**, so item
    composition applies it to the consuming member today, and a future
    admin `/effect apply` can apply it to any member/guild. Pog and
    Froggers are the same effect: both publish to the single
    ``(scope, seam, source)`` row under the shared effect identity
    ``FrogEffect.REACTION`` — never per-item sources — and the granting
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
        payload: EffectPayload,
        *,
        uid: int,
        species_key: FrogItemKey,
        now: pendulum.DateTime,
    ) -> None:
        """No catch behavior — the effect applies on consume only."""
        return None

    async def consume(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        scope: Scope,
        provenance: str,
        amount: int,
        now: pendulum.DateTime,
    ) -> None:
        """Publish/merge the shared reaction effect into ``scope``."""
        if not isinstance(payload, ReactionPayload):
            raise TypeError(
                "reaction effect requires ReactionPayload, got "
                f"{type(payload).__name__}"
            )
        seam = FrogSeam.FROG_REACTION
        source = FrogEffect.REACTION.key
        prov: dict[str, object] = {
            "chance": payload.chance,
            "from": provenance,
        }
        existing = await bot.effects.fetch(scope, seam, source, now=now)
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
            await bot.effects.publish(
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
            await bot.effects.publish(
                scope,
                seam,
                source,
                prov,
                duration=payload.duration,
                policy=ReapplyPolicy.EXTEND,
                now=now,
            )


class RoleEffect:
    """``role`` — a generic, composable state modifier: publish the one
    classy-role effect for a Scope.

    ``FrogSeam.CLASSY_ROLE`` is an external seam: ``Effects.publish``
    runs the RoleConverger synchronously (role added now) and schedules
    the converge job at expiry (role removed then); explicit clear
    reverts instantly via EffectsClearedEvent. Normal and frozen Classy
    are the same effect (one row, EXTEND rolls the duration); the
    guild-side role id is resolved here from ``bot.config.guild_kind`` so
    the stored payload is the concrete role the converger must converge
    to, with the granting item as provenance. Scope-aware like every
    modifier — item composition passes the member scope; a future admin
    command could target any member.
    """

    async def catch(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        uid: int,
        species_key: FrogItemKey,
        now: pendulum.DateTime,
    ) -> None:
        """No catch behavior — the effect applies on consume only."""
        return None

    async def consume(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        scope: Scope,
        provenance: str,
        amount: int,
        now: pendulum.DateTime,
    ) -> None:
        """Publish the role grant into ``scope``."""
        if not isinstance(payload, RolePayload):
            raise TypeError(
                "role effect requires RolePayload, got "
                f"{type(payload).__name__}"
            )
        role_id = payload.role_id_for(bot.config.guild_kind)
        await bot.effects.publish(
            scope,
            FrogSeam.CLASSY_ROLE,
            source=FrogEffect.CLASSY_ROLE.key,
            payload={"role_id": role_id, "from": provenance},
            duration=payload.duration,
            policy=ReapplyPolicy.EXTEND,
            now=now,
        )


class RoleConverger:
    """World-reconciliation for the CLASSY_ROLE seam (member roles).

    Registered via ``bot.effects.register_converger`` at plugin load
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
        ``effects``, so ``effects`` never imports ``species`` — the edge
        ``species → effects`` stays one-way).
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
        contribs = await bot.effects.list(scope, FrogSeam.CLASSY_ROLE)
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
        reason = "classy frog role effect"
        for role_id in wanted - current:
            await bot.rest.add_role_to_member(
                bot.config.guild_id, scope.id, role_id, reason=reason
            )
        for role_id in (current & self._known_role_ids()) - wanted:
            await bot.rest.remove_role_from_member(
                bot.config.guild_id, scope.id, role_id, reason=reason
            )


class EffectKey(Enum):
    """The effect registry — each member's value IS its handler.

    ``EXP`` is the pre-composition fossil: consume-side exp is item-owned
    behavior (the oracle in ``items.py``), so it is composed into nothing
    and slated for removal. ``REACTION``/``ROLE`` are the generic,
    scope-aware consume modifiers (2026-08-28 separation): any caller —
    item composition today, an admin command tomorrow — applies them to
    any member/guild scope. Adding an effect = define the handler class,
    then one enum member; dispatch everywhere is ``payload.key.value``
    and needs no registration or lookup.
    """

    EXP = ExpEffect()
    REACTION = ReactionEffect()
    ROLE = RoleEffect()


@dataclass(frozen=True, slots=True)
class ExpPayload:
    """The ``exp`` consume effect's configuration (a fossil).

    ``exp`` is the value per frog in the normal state, ``frozen_exp`` the
    value when consumed frozen (the default species preserves the legacy
    10/3). Slated for removal with :class:`ExpEffect`: live consume-exp
    values live in the item oracle (``items.py::frog_exp``) — this
    payload predates the item-owned composition split.
    """

    key = EffectKey.EXP

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
    """The ``reaction`` consume effect's configuration.

    ``chance`` is the strongest-wins value merged into the shared
    frog-reaction seam row; ``duration`` is the additive window rolled
    on every consume (FROG.md: "only the duration is increased, never a
    stronger effect").
    """

    key = EffectKey.REACTION

    chance: float
    duration: timedelta


@dataclass(frozen=True, slots=True)
class RolePayload:
    """The ``role`` consume effect's configuration — the classy role.

    FROG.md's two role ids, one per guild side; ``duration`` is the
    grant's lifetime (EXTEND rolls it on re-consume).
    """

    key = EffectKey.ROLE

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
