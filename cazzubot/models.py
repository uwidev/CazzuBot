"""Shared enums (values are stored as TEXT in sqlite) and plain value types."""

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class MemberSnapshot:
    """The member fields a message template can interpolate.

    Plain values only — the framework-agnostic replacement for passing a
    stateful ``discord.Member``/``User`` into service-layer formatters.
    Build one at the controller edge with ``utils.member_snapshot``.
    """

    id: int
    display_name: str
    mention: str
    avatar_url: str


class WindowEnum(Enum):
    SEASONAL = "seasonal"
    LIFETIME = "lifetime"


class MemberExpLogSourceEnum(Enum):
    MESSAGE = "message"
    FROG = "frog"


class FrogState(Enum):
    """A frog inventory state — per species, per member."""

    NORMAL = "normal"
    FROZEN = "frozen"


class SpeciesKey(Enum):
    """The valid frog species keys — code references them, never strings.

    Lives next to ``FrogState`` because both are stored as TEXT and shared
    across the frogs plugin's modules (and future consumers like badges).
    """

    LEAF_FROG = "leaf_frog"
    CLASSY_FROG = "classy_frog"


class WelcomeModeEnum(Enum):
    PENDING = "pending"
    ROLE = "role"


class ModlogTypeEnum(Enum):
    WARN = "warn"
    MUTE = "mute"
    KICK = "kick"
    TEMPBAN = "tempban"
    BAN = "ban"


class ModlogStatusEnum(Enum):
    ACTIVE = "active"
    PARDONED = "pardoned"
    DELETED = "deleted"
