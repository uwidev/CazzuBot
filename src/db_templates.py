"""Holds all entry templates for the database.

Templates are usually in the form of classes, but their true form is in the form of
dict. Templates need to be separated from their cog extension because when being loaded,
they get re-defined, creating a new ID, and makes isinstance() false, despite appearing
to be the same class. This has negative implications, especially when trying to
decode json data back into their proper class.

TODO Figure out a more elegant solution for creating new settings and their defaults.
TODO See if you can leverage the Setting class.
"""
import logging
from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from pendulum import DateTime

from src.attributemap import AttributeMap
from src.setting_namespace import GuildSettingScope, ModLogStatus, ModLogType


_log = logging.getLogger(__name__)


class TaskEntry(AttributeMap):
    """Abstract class for a task in the database."""

    def __init__(self, module: str, data: Mapping = {}):
        self.module = module
        super().__init__(data)


class ModLogTaskEntry(TaskEntry):
    gid: int
    uid: int
    expires_on: DateTime
    log_type: DateTime

    def __init__(self, gid: str, uid: str, log_type: ModLogType, expires_on: str):
        super().__init__("MODLOG")
        self.gid = gid
        self.uid = uid
        self.expires_on = expires_on
        self.log_type = log_type


class ModLogEntry(AttributeMap):
    # uid: int
    # uid: int
    # cid: int
    # log_type: ModLogType
    # given_on: DateTime
    # expires_on: DateTime
    # reason: str
    # status: ModLogStatus

    def __init__(  # noqa: PLR0913
        self,
        uid: int,
        gid: int,
        cid: int,
        log_type: ModLogType,
        given_on: DateTime,
        expires_on: DateTime,
        reason: str = None,
        status: ModLogStatus = 0,
    ) -> None:
        self.uid = uid
        self.gid = gid
        self.cid = cid
        self.log_type = log_type
        self.given_on = given_on
        self.expires_on = expires_on
        self.reason = reason
        self.status = status


class GuildSettingDefault(AttributeMap):
    def __init__(self, data):
        self.__dict__[data["name"]] = data


# Setings of other extensions should be prefixed.
# e.g. for the moderation extension
# setting = mod.mute_role
@dataclass
class GuildSetting(AttributeMap):
    """A setting object that is used to insert into the database."""

    name: str
    value: Any
    gid: int = None
    scope: GuildSettingScope = None
    defaults: ClassVar[dict] = {}

    @classmethod
    def register_defaults(cls, payload: GuildSettingDefault):
        cls.defaults.update(payload)
