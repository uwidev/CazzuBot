"""Helper management and typing for modlog entry."""

from enum import Enum

import pendulum
from tinydb import TinyDB

import src.db_interface as dbi
from src.future_time import FutureTime
from src.utility import ReadOnlyDict


TASKS = ReadOnlyDict({})

# pardoned means that it doesn't count towards historical infractions
# deleted means it will no longer appear, unless forced
LOG_ENTRY = ReadOnlyDict(
    {
        "gid": None,
        "uid": None,
        "cid": None,
        "type": None,
        "given_on": None,
        "expires_on": None,
        "reason": None,
        "pardoned": False,
        "deleted": False,
    }
)


class LogType(Enum):
    WARN = "warn"
    MUTE = "mute"
    KICK = "kick"
    BAN = "ban"


class ModLog:
    def __init__(  # noqa: PLR0913
        self,
        uid: int,
        gid: int,
        cid: int,
        log_type: LogType,
        now: pendulum.DateTime,
        expires_on: FutureTime,
        reason: str,
    ) -> None:
        self.uid = uid
        self.gid = gid
        self.cid = cid
        self.log_type = log_type.value
        self.given_on = now.to_iso8601_string()
        self.expires_on = expires_on.to_iso8601_string()
        self.reason = reason

    def as_dict(self) -> dict:
        return self.__dict__


def get_next_case_id(db: TinyDB, gid: int):
    modlogs = dbi.get_guild_modlog(db, gid)
    if not modlogs:
        return 1

    return sorted(case["cid"] for case in modlogs)[-1] + 1
