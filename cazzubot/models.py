"""Shared enums (values are stored as TEXT in sqlite)."""

from enum import Enum


class WindowEnum(Enum):
    SEASONAL = "seasonal"
    LIFETIME = "lifetime"


class MemberExpLogSourceEnum(Enum):
    MESSAGE = "message"
    FROG = "frog"


class FrogTypeEnum(Enum):
    NORMAL = "normal"
    FROZEN = "frozen"


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
