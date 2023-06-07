"""
This script serves as a handler for registering per-cog settings into the
the database.

Values should be already converted to appropriate types.
"""
import logging
from enum import Enum

from utility import ReadOnlyDict


GUILD_TEMPLATE_SETTINGS = {
    'DEFAULT': {},
    'GLOBAL': {},
    'ROLE': {},
    'CHANNEL': {},
    'USER': {},
}


USER_TEMPLATE_SETTINGS = {
    'DEFAULT': {},
    'GLOBAL': {},
    'GUILD': {},
    'CHANNEL': {},
}


GUILD_TEMPLATE_MODLOGS = {

}


class Table(Enum):
    """Enum mapping from database name to their schema."""
    GUILD_SETTINGS = GUILD_TEMPLATE_SETTINGS
    GUILD_MODLOGS = GUILD_TEMPLATE_MODLOGS
    USER_EXPERIENCE = USER_TEMPLATE_SETTINGS


class Scope(Enum):
    """Allowed scopes for settings, ordered smallest to largest."""
    USER = 'USER'
    CHANNEL = 'CHANNEL'
    ROLE = 'ROLE'
    GUILD = 'guild'
    GLOBAL = 'GLOBAL'
    DEFAULT = 'DEFAULT'


def register_settings(table: Table, scope: Scope, settings: dict):
    """Adds the given setting format to the bot settings at runtime."""
    if scope.value not in table.value.keys():
        raise UnsupportedScope(table, scope)

    table.value[scope.value].update(settings)


class UnsupportedScope(ValueError):
    def __init__(self, table, Table, scope: Scope):
        msg = (f'Scoping of {scope.value} is not supported on table ',
               f'{table.name}')
        super().__init__(msg)
