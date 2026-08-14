"""Frog species effects — a typed, payload-driven effect registry.

Effects are fully decoupled from the species and the controllers:

- Each effect owns a **payload dataclass** — its configuration. A species
  definition carries payload *instances* (``catch_effect`` /
  ``consume_effect``), so one effect class is reusable with different
  values (the ``exp`` effect powers both the 10/3 Leaf Frog and the 20/6
  Classy Frog), and a species never carries fields for effects it doesn't
  use.
- A payload's ``key`` is an :class:`EffectKey` enum member, and **the
  enum IS the registry**: each member's value is its handler object.
  ``payload.key.value`` is the effect with its ``catch``/``consume``
  hooks — dispatch is a plain attribute access, no lookup table, so a key
  without a handler cannot exist (the LSP guarantee is structural, not a
  test).
- Hooks receive the **bot** plus the payload, so an effect can do
  anything — grant exp, schedule a cluster of frogs across channels, hand
  out roles — without the cog or factory knowing about it.

No hikari imports: ``bot`` is only a parameter (TYPE_CHECKING-annotated);
effects reach services through it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

import pendulum

from cazzubot.models import FrogState, MemberExpLogSourceEnum, SpeciesKey

from plugins.experience import db as exp_db

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)


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

    Hooks receive the bot, the species' payload instance for this effect,
    and the plain context (uid / species / amount / state / now). Unused
    hooks are no-ops; a species with no effect on a side leaves that side
    None.
    """

    async def catch(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        uid: int,
        species_key: SpeciesKey,
        now: pendulum.DateTime,
    ) -> None: ...

    async def consume(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        uid: int,
        species_key: SpeciesKey,
        amount: int,
        state: FrogState,
        now: pendulum.DateTime,
    ) -> None: ...


class ExpEffect:
    """``exp`` — consume: seasonal exp per payload values."""

    async def catch(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        uid: int,
        species_key: SpeciesKey,
        now: pendulum.DateTime,
    ) -> None:
        return None  # no catch behavior

    async def consume(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        uid: int,
        species_key: SpeciesKey,
        amount: int,
        state: FrogState,
        now: pendulum.DateTime,
    ) -> None:
        if not isinstance(payload, ExpPayload):
            raise TypeError(
                "exp effect requires ExpPayload, got "
                f"{type(payload).__name__}"
            )
        exp_per = (
            payload.frozen_exp
            if state is FrogState.FROZEN
            else payload.exp
        )
        await exp_db.add_exp_log(
            bot.db,
            uid,
            exp_per * amount,
            now,
            source=MemberExpLogSourceEnum.FROG,
        )


class EffectKey(Enum):
    """The effect registry — each member's value IS its handler.

    Adding an effect = define the handler class, then one enum member
    (``CLUSTER = ClusterEffect()``); dispatch everywhere is
    ``payload.key.value`` and needs no registration or lookup.
    """

    EXP = ExpEffect()


@dataclass(frozen=True, slots=True)
class ExpPayload:
    """The ``exp`` consume effect's configuration.

    ``exp`` is the value per frog in the normal state, ``frozen_exp`` the
    value when consumed frozen (the default species preserves the legacy
    10/3).
    """

    key = EffectKey.EXP

    exp: int
    frozen_exp: int
