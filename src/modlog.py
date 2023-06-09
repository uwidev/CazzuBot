"""Helper management and typing for modlog entry."""

from enum import Enum

from src.future_time import FutureTime
from src.utility import ReadOnlyDict


MODLOG_ENTRY_TEMPLATE = ReadOnlyDict(
    {
        "id": None,
        "uid": None,
        "type": None,
        "given_at": None,
        "duration": None,
        "expires": None,
        "reason": None,
    }
)


class LogType(Enum):
    WARN = "warn"
    MUTE = "mute"
    KICK = "kick"
    BAN = "ban"


def modlog(uid: int, type: LogType, until: FutureTime, reason: str) -> dict:
    log = dict(MODLOG_ENTRY_TEMPLATE)
    log["uid"] = uid


class ModLog:
    def __init__(
        self, uid: int, log_type: LogType, until: FutureTime, reason: str
    ) -> None:
        self.uid = uid
        self.log_type = log_type.value
        self.until = until.to_iso8601_string()
        self.reason = reason
