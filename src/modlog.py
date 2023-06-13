"""Helper management and typing for modlog entry."""

from enum import Enum, Flag, auto

from aiotinydb import AIOTinyDB
from pendulum import DateTime

import src.db_interface as dbi
from src.task_manager import TaskEntry


class ModLogStatus(Flag):
    PARDONED = auto()
    DELETED = auto()


class ModLogType(Enum):
    WARN = "warn"
    MUTE = "mute"
    KICK = "kick"
    BAN = "ban"


class ModLogTask(TaskEntry):
    def __init__(self, gid: str, uid: str, log_type: ModLogType, expires_on: str):
        super().__init__("MODLOG")
        self.gid = gid
        self.uid = uid
        self.expires_on = expires_on
        self.log_type = log_type


class ModLogEntry:
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


async def add_modlog(db: AIOTinyDB, modlog: ModLogEntry):
    await dbi.insert_document(db, "MODLOG", modlog)


async def get_next_log_id(db: AIOTinyDB, gid: int):
    modlogs = await dbi.get_guild_modlog(db, gid)
    if not modlogs:
        return 1

    return sorted(log["cid"] for log in modlogs)[-1] + 1
