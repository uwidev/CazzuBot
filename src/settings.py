"""A guild's settings."""
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from aiotinydb import AIOTinyDB
from tinydb import where

import src.db_interface as dbi
from src.attributemap import AttributeMap


_log = logging.getLogger(__name__)


@dataclass
class Settings(AttributeMap):
    """Alias for AttributeMap.

    Schema is as follows.
    setting_name={value=value, scope=None/Guild/Role/Channel/User, id=id}

    Modules are meant to inherit from this class when defining settings, and used to
    update the bot's guild_defaults on setup. When writing to database, we need to only
    write the differences of what we're setting and the defaults.

    Unfortunately, we cannot decode from database middleware, so will need to convert
    id according to scope when needed.
    """

    name: str
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        name = self.name
        data = self.data
        self.__dict__.clear()
        self.__dict__.update({name: data})

    def __repr__(self) -> str:
        return self._repr("Settings")


@dataclass
class Guild(AttributeMap):
    """Defines all settings for a guild.

    On bot startup, it should create an instance of this and assign it to some member
    variable (e.g. bot.guild_defaults). When extensions are loaded, cogs should register
    their defaults settings to the bot. Afterwards, be sure to lock the map to prevent
    any modifications.
    """

    gid: int = None
    _settings: AttributeMap = field(default_factory=AttributeMap)
    _locked: bool = False

    def update(self, settings: Settings):
        if self._locked:
            raise LockedMappingError(self)
        self._settings.update(settings)

    def lock(self):
        self._locked = True

    def unlock(self):
        self._locked = False

    def __setitem__(self, key: Any, value: Any) -> None:
        if self._locked:
            raise LockedMappingError(self)
        return super().__setitem__(key, value)

    def __setattr__(self, key: str, value: Any) -> None:
        if self._locked:
            raise LockedMappingError(self)
        return super().__setattr__(key, value)

    def __repr__(self) -> str:
        return self._repr("GuildSettings")


class LockedMappingError(Exception):
    def __init__(self, mapping: Mapping):
        msg = "Cannot write to locked Mapping: {mapping}"
        super().__init__(repr(msg))


async def write(db: AIOTinyDB, gid: int, settings: Guild):
    """Write the entirety of given guild's settings onto the database.

    Requires settings defaults to be passed.
    """
    guild_settings = Guild(gid, settings)

    return await dbi._upsert(
        db,
        dbi.Table.GUILD_SETTING,
        guild_settings.as_dict(),
        where("gid") == gid,
    )
