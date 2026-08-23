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
    """The leaderboard time window: seasonal or lifetime."""

    SEASONAL = "seasonal"
    LIFETIME = "lifetime"


class MemberExpLogSourceEnum(Enum):
    """The source of an exp-log entry: message earned or frog awarded."""

    MESSAGE = "message"
    FROG = "frog"


class FrogState(Enum):
    """A frog inventory state — per species, per member."""

    NORMAL = "normal"
    FROZEN = "frozen"


class FrogItemKey(Enum):
    """The valid frog species keys — code references them, never strings.

    Lives next to ``FrogState`` because both are stored as TEXT and shared
    across the frogs plugin's modules (and future consumers like badges).
    """

    BASIC = "basic"


class WelcomeModeEnum(Enum):
    """Welcome handling mode: pending approval or auto role grant."""

    PENDING = "pending"
    ROLE = "role"


class ModlogTypeEnum(Enum):
    """The moderation action a modlog entry records."""

    WARN = "warn"
    MUTE = "mute"
    KICK = "kick"
    TEMPBAN = "tempban"
    BAN = "ban"


class ModlogStatusEnum(Enum):
    """Lifecycle state of a modlog entry."""

    ACTIVE = "active"
    PARDONED = "pardoned"
    DELETED = "deleted"
