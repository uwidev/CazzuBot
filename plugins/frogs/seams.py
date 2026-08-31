"""Frog status seams — typed keys, never bare strings (SeamKey pattern).

Mirrors ``plugins/experience/logic.py::StatusSeam``: the enum member's
``key`` is the stored seam string; ``external`` marks seams whose
consequence touches Discord (only those get convergence jobs).
"""

from __future__ import annotations

from enum import Enum


class FrogSeam(Enum):
    """Frogs' input points on the statuses engine."""

    # internal: message-time reaction chance (lazy expiry, no converger)
    FROG_REACTION = "frog_reaction"
    # external: a Discord role granted for a duration (converged by
    # plugins/frogs/outcomes.py::RoleConverger)
    CLASSY_ROLE = "classy_role"

    @property
    def key(self) -> str:
        """The derived storage string for this seam."""
        return self.value

    @property
    def external(self) -> bool:
        """True when the seam needs world-convergence (a Discord side effect)."""
        return self is FrogSeam.CLASSY_ROLE


class FrogStatus(Enum):
    """Frog status identities — the `source` of a contribution.

    "The same status" is keyed by (scope, seam, source); several items
    that publish the same status (Pog and Froggers = reaction chance) share
    one identity here, and the granting item travels in the payload as
    ``"from"`` provenance — the item never defines identity.
    """

    REACTION = "frog_reaction"
    CLASSY_ROLE = "classy_role"

    @property
    def key(self) -> str:
        """The derived storage string for this status identity."""
        return self.value
