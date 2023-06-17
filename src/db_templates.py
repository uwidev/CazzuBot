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

from pendulum import DateTime

from src.attributemap import AttributeMap
from src.setting_namespace import ModLogStatus, ModLogType


_log = logging.getLogger(__name__)


@dataclass
class TaskEntry(AttributeMap):
    """Abstract class for a task in the database."""

    tag: str  # identifier for querying of specfic handlers
    run_at: DateTime

    def __repr__(self) -> str:
        return self._repr("GuildSettings")


@dataclass
class ModLogTaskEntry(TaskEntry):
    gid: int
    uid: int
    log_type: ModLogType

    def __repr__(self) -> str:
        return self._repr("ModLogTaskEntry")


@dataclass
class ModLogEntry(AttributeMap):
    uid: int
    gid: int
    cid: int
    log_type: ModLogType
    given_on: DateTime
    expires_on: DateTime
    reason: str
    status: ModLogStatus = 0

    def __repr__(self) -> str:
        return self._repr("ModLogEntry")
