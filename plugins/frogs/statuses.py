"""Frog statuses — unique status effects, values owned by the class.

Stored strings tie to nothing outside this module: ``Status.key`` is the
contribution ``source``; ``FrogSeam`` is the seam the status fills. The
old ``FrogStatus`` identity enum is gone — the status class IS the
identity.

A status class owns every value of its effect (chance, duration, role
ids, reapply policy, priority); the store records only the contribution
(provenance = the granting item id). A feature's pull maps a row's
``source`` back to its class via :func:`status_by_source` and reads the
values off the class — single source of truth, no payload drift.

Role-granting statuses (:class:`RoleStatus`) implement the core role-grant
contract (``role_id_for(guild_kind)``), so the generic core
:class:`~cazzubot.statuses.RoleConverger` reconciles the CLASSY_ROLE
seam's world state; it is registered on the plugin at load
(``plugins/frogs/__init__.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from typing_extensions import override

from cazzubot.statuses import (
    Status,
    register_status,
)

from .seams import FrogSeam


@dataclass(frozen=True, slots=True, kw_only=True)
class ReactionStatus(Status):
    """A reaction-chance status: consume grants the shared react seam."""

    chance: float
    cooldown_seconds: int = 10

    @override
    def describe(self) -> str:
        window = _describe_duration(self.duration)
        return (
            f"For {window}, a **{self.chance:.0%}** chance the bot "
            f"reacts to your messages with the froggers emoji "
            f"({self.cooldown_seconds}s cooldown)."
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleStatus(Status):
    """A role-grant status: the classy frog's external world consequence.

    Exposes ``role_id_for(guild_kind)`` — the structural role-grant
    contract the core :class:`~cazzubot.statuses.RoleConverger` reads, so
    no frog-side converger is needed for this seam.
    """

    role_dev: int
    role_prod: int

    def role_id_for(self, guild_kind: str) -> int:
        """The concrete role id for the guild side (FROG.md's two ids)."""
        return (
            self.role_dev
            if guild_kind == "development"
            else self.role_prod
        )

    @override
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


# -- the frog statuses (one unique class per declared status) --------------

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


register_frog_statuses()
