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


@dataclass
class Guild(SnowflakeTable):
    gid: int
    mute_role: int = None
    ranks: dict = field(default_factory=dict)

    def conflicts(self) -> str:
        return "(gid)"

    def __iter__(self):
        return iter([self.gid, self.mute_role])


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


@dataclass
class Modlog(SnowflakeTable):
    gid: int
    uid: int
    cid: int
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
class Task(SnowflakeTable):
    tag: list
    run_at: pendulum.DateTime
    payload: dict
    id: int = None

    def __iter__(self):
        return iter([self.tag, self.run_at, self.payload])


@dataclass
class Member(SnowflakeTable):
    gid: int  # REFERNECES guild.gid
    uid: int  # REFERENCES user.uid
    exp_lifetime: int = 0
    exp_msg_cnt: int = 0
    exp_cdr: pendulum.DateTime = None

    def __iter__(self):
        """Unpacking for inserting new row."""
        return iter(
            [self.gid, self.uid, self.exp_lifetime, self.exp_msg_cnt, self.exp_cdr]
        )


@dataclass
class User(SnowflakeTable):
    uid: int

    def __iter__(self):
        """Unpacking for inserting new row."""
        return iter([self.uid])


@dataclass
class MemberExpLog(SnowflakeTable):
    gid: int  # REFERENCES guild.gid
    uid: int  # REFERENCES user.uid
    exp: int
    at: pendulum.DateTime

    def __iter__(self):
        return iter([self.gid, self.uid, self.exp, self.at])


@dataclass
class RankThreshold(SnowflakeTable):
    gid: int  # REFERENCES guild.gid
    rid: int
    threshold: int
    mode: WindowEnum

    def __iter__(self):
        return iter([self.gid, self.rid, self.threshold, self.mode])


@dataclass
class Rank(SnowflakeTable):
    gid: int  # REFERENCES guild.gid
    message: str  # encoded json, default already set in db
    mode: WindowEnum

    def __iter__(self):
        return iter([self.gid, self.message, self.mode])


@dataclass
class Level(SnowflakeTable):
    gid: int  # REFERENCES guild.gid
    message: str  # encoded json, default already set in db

    def __iter__(self):
        return iter([self.gid])


@dataclass
class Frog(SnowflakeTable):
    gid: int
    cid: int
    interval: int
    duration: int
    fuzzy: float

    def __iter__(self):
        return iter([self.gid, self.cid, self.interval, self.duration, self.fuzzy])
