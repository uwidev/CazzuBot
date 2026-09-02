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
    # external: a Discord role granted for a duration (converged by the
    # core cazzubot.statuses::RoleConverger, registered by the plugin)
    CLASSY_ROLE = "classy_role"

    @property
    def key(self) -> str:
        """The derived storage string for this seam."""
        return self.value

    @property
    def external(self) -> bool:
        """True when the seam needs world-convergence (a Discord side effect)."""
        return self is FrogSeam.CLASSY_ROLE
