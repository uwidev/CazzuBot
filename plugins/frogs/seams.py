"""Frog effect seams — typed keys, never bare strings (SeamKey pattern).

Mirrors ``plugins/experience/logic.py::EffectSeam``: the enum member's
``key`` is the stored seam string; ``external`` marks seams whose
consequence touches Discord (only those get convergence jobs).
"""

from __future__ import annotations

from enum import Enum


class FrogSeam(Enum):
    """Frogs' input points on the effects engine."""

    # internal: message-time reaction chance (lazy expiry, no converger)
    FROG_REACTION = "frog_reaction"
    # external: a Discord role granted for a duration (converged by
    # plugins/frogs/effects.py::RoleConverger)
    CLASSY_ROLE = "classy_role"

    @property
    def key(self) -> str:
        """The derived storage string for this seam."""
        return self.value

    @property
    def external(self) -> bool:
        """True when the seam needs world-convergence (a Discord side effect)."""
        return self is FrogSeam.CLASSY_ROLE


class FrogEffect(Enum):
    """Frog effect identities — the `source` of a contribution.

    "The same effect" is keyed by (scope, seam, source); several items
    that ARE the same effect (Pog and Froggers = reaction chance) share
    one identity here, and the granting item travels in the payload as
    ``"from"`` provenance — the item never defines identity.
    """

    REACTION = "frog_reaction"
    CLASSY_ROLE = "classy_role"

    @property
    def key(self) -> str:
        """The derived storage string for this effect identity."""
        return self.value