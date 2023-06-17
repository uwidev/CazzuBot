"""Contains mappings of enums to their appropriate setting name."""
from enum import Enum, Flag, auto


# ========================
# mod.py
# ========================


class ModSettingName(Enum):
    MUTE_ROLE = "mod.mute_role"


class ModLogStatus(Flag):
    PARDONED = auto()
    DELETED = auto()


class ModLogType(Enum):
    WARN = "warn"
    MUTE = "mute"
    KICK = "kick"
    BAN = "ban"


# ========================
# Settings/Permissions
# ========================


class GuildSettingScope(Enum):  # Will need to create a way to resolve scope settings.
    DEFAULT = auto()
    GUILD = auto()
    CHANNEL = auto()
    ROLE = auto()
    USER = auto()
