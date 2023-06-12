"""Serves as a handler for registering per-cog settings into the database.

Values should be already converted to appropriate types.
"""
from enum import Enum


# Settings are resolved...?
#
# Current idea is to almost have this like a chainmap, such that field-values set on
# narrower scopes have precedent over broader scopes.
GUILD_TEMPLATE_SETTINGS = {
    "DEFAULT": {},
    "GLOBAL": {},
    "ROLE": {},
    "CHANNEL": {},
    "USER": {},
}

# Uh... see above.
USER_TEMPLATE_SETTINGS = {
    "DEFAULT": {},
    "GLOBAL": {},
    "GUILD": {},
    "CHANNEL": {},
}

# Stores a mapping of module -> time to run at -> data
# Task should contain all data needed to execute the task, which should be defined at
# the given module.
TASKS = {}

# Stores a mapping of guild id -> user id -> ModLog
GUILD_TEMPLATE_MODLOGS = {}


class Table(Enum):
    """Enum mapping from database name to their schema."""

    GUILD_SETTINGS = GUILD_TEMPLATE_SETTINGS
    GUILD_MODLOGS = GUILD_TEMPLATE_MODLOGS
    USER_EXPERIENCE = USER_TEMPLATE_SETTINGS


class Scope(Enum):
    """Allowed scopes for settings, ordered smallest to largest."""

    USER = "USER"
    CHANNEL = "CHANNEL"
    ROLE = "ROLE"
    GUILD = "guild"
    GLOBAL = "GLOBAL"
    DEFAULT = "DEFAULT"


def register_settings(table: Table, scope: Scope, settings: dict):
    """Register passed settings onto main settings dict."""
    if scope.value not in table.value.keys():
        raise UnsupportedScopeError(table, scope)

    table.value[scope.value].update(settings)


class UnsupportedScopeError(ValueError):
    def __init__(self, table: Table, scope: Scope):
        msg = (f"Scoping of {scope.value} is not supported on table ", f"{table.name}")
        super().__init__(msg)
