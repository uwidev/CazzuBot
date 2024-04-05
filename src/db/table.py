"""Defines schema for databases for autocomplete."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

import pendulum


class SnowflakeTable(ABC):
    def columns(self):
        """Return columns to dump into."""
        return "(" + ", ".join(self.__dict__.keys()) + ")"

    def values(self):
        """Return values to write to columns."""
        joined = ", ".join(map(str, self.__dict__.values())).replace("None", "NULL")
        return f"({joined})"

    def upsert(self) -> str:
        """Return a string to designate upsert writing of new values."""
        pairs = []
        for k, v in zip(self.__dict__.keys(), self.__dict__.keys()):
            pairs.append(f"{k} = EXCLUDED.{v}")
        return ", ".join(pairs)

    def conflicts(self) -> str:
        """Overwrite to return conflicts to watch out for, mainly primary keys."""

    @abstractmethod
    def __iter__(self):
        """Return an iterable of the datatype, mainly used for unpacking.

        In order to unpack correctly, you must explicitly state the order to unpack.
        """


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


class WindowEnum(Enum):
    SEASONAL = "seasonal"
    LIFETIME = "lifetime"


class MemberExpLogSourceEnum(Enum):
    MESSAGE = "message"
    FROG = "frog"


class FrogTypeEnum(Enum):
    NORMAL = "normal"
    FROZEN = "frozen"


@dataclass
class Task(SnowflakeTable):
    tag: list
    run_at: pendulum.DateTime
    payload: dict
    id: int = None

    def __iter__(self):
        return iter([self.tag, self.run_at, self.payload])


@dataclass
class Guild(SnowflakeTable):
    gid: int
    mute_role: int = None

    def conflicts(self) -> str:
        return "(gid)"

    def __iter__(self):
        return iter([self.gid, self.mute_role])


@dataclass
class User(SnowflakeTable):
    uid: int

    def __iter__(self):
        """Unpacking for inserting new row."""
        return iter([self.uid])


@dataclass
class Channel(SnowflakeTable):
    gid: int  # references guild.gid
    cid: int

    def __iter__(self):
        return iter([self.gid, self.cid])


@dataclass
class Role(SnowflakeTable):
    gid: int  # references guild.gid
    rid: int

    def __iter__(self):
        return iter([self.gid, self.rid])


@dataclass
class Member(SnowflakeTable):
    gid: int  # references guild.gid
    uid: int  # references user.uid

    def __iter__(self):
        return iter([self.gid, self.uid])


@dataclass
class Modlog(SnowflakeTable):
    gid: int  # references member.gid
    uid: int  # references member.uid
    case: int
    log_type: ModlogTypeEnum
    given_on: pendulum.DateTime
    expires_on: pendulum.DateTime = None
    reason: str = None
    status: ModlogStatusEnum = ModlogStatusEnum.ACTIVE

    def conflicts(self) -> str:
        return "(gid)"

    def __iter__(self):
        """When unpacking, don't use cid since it's serialized (auto-increments)."""
        return iter(
            [
                self.gid,
                self.uid,
                self.log_type,
                self.given_on,
                self.status,
                self.expires_on,
                self.reason,
            ]
        )


@dataclass
class RankThreshold(SnowflakeTable):
    gid: int  # references role.gid
    rid: int  # references role.rid
    threshold: int
    mode: WindowEnum

    def __iter__(self):
        return iter([self.gid, self.rid, self.threshold, self.mode])


@dataclass
class Rank(SnowflakeTable):
    gid: int  # references guild.id
    message: str  # encoded json, default already set in db
    mode: WindowEnum

    def __iter__(self):
        return iter([self.gid, self.message, self.mode])


@dataclass
class Level(SnowflakeTable):
    gid: int  # references guild.id
    message: str  # encoded json, default already set in db

    def __iter__(self):
        return iter([self.gid])


@dataclass
class FrogSpawn(SnowflakeTable):
    gid: int  # references channel.gid
    cid: int  # references channel.cid
    interval: int
    persist: int
    fuzzy: float

    def __iter__(self):
        return iter([self.gid, self.cid, self.interval, self.persist, self.fuzzy])


@dataclass
class Frog(SnowflakeTable):
    gid: int  # references guild.gid
    message: dict
    enabled: bool

    def __iter__(self):
        return iter([self.gid, self.message, self.enabled])


@dataclass
class MemberFrog(SnowflakeTable):
    gid: int  # references member.gid
    uid: int  # references member.uid
    normal: int = 0
    frozen: int = 0

    def __iter__(self):
        """Unpacking for inserting new row."""
        return iter([self.gid, self.gid, self.gid, self.normal, self.frozen])


@dataclass
class MemberExp(SnowflakeTable):
    gid: int  # references member.gid
    uid: int  # references member.uid
    lifetime: int = 0
    msg_cnt: int = 0
    cdr: pendulum.DateTime = None

    def __iter__(self):
        """Unpacking for inserting new row."""
        return iter([self.gid, self.uid, self.lifetime, self.msg_cnt, self.cdr])


@dataclass
class MemberExpLog(SnowflakeTable):
    gid: int  # REFERENCES guild.gid
    uid: int  # REFERENCES user.uid
    exp: int
    at: pendulum.DateTime
    source: MemberExpLogSourceEnum = MemberExpLogSourceEnum.MESSAGE

    def __iter__(self):
        return iter([self.gid, self.uid, self.exp, self.at, self.source])


@dataclass
class MemberFrogLog(SnowflakeTable):
    """Log when a user captures a frog."""

    gid: int
    uid: int
    type: FrogTypeEnum
    at: pendulum.DateTime = None
    waited_for: float = None

    def __iter__(self):
        return iter([self.gid, self.uid, self.type, self.at, self.waited_for])
