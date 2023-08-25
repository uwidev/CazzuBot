"""Defines schema for databases for autocomplete."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto

import pendulum


class PGEnum(Enum):
    """Force string coversion to convert it's enum name, rather than full."""

    def __str__(self):
        return self.name


class SnowflakeSchema(ABC):
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
class GuildSettings(SnowflakeSchema):
    gid: int
    mute_role: int = None

    def conflicts(self) -> str:
        return "(gid)"

    def __iter__(self):
        return iter([self.gid, self.mute_role])


class ModlogTypeEnum(PGEnum):
    WARN = "warn"
    MUTE = "mute"
    KICK = "kick"
    TEMPBAN = "tempban"
    BAN = "ban"


class ModlogStatusEnum(PGEnum):
    ACTIVE = "active"
    PARDONED = "pardoned"
    DELETED = "deleted"


@dataclass
class Modlog(SnowflakeSchema):
    gid: int
    uid: int
    cid: int
    log_type: ModlogTypeEnum
    given_on: pendulum.DateTime
    expires_on: pendulum.DateTime
    status: ModlogStatusEnum = ModlogStatusEnum.ACTIVE

    def conflicts(self) -> str:
        return "(gid)"

    def __iter__(self):
        return iter(
            [
                self.gid,
                self.uid,
                self.cid,
                self.log_type,
                self.given_on,
                self.expires_on,
                self.status,
            ]
        )


@dataclass
class Task(SnowflakeSchema):
    tag: list
    run_at: pendulum.DateTime
    payload: dict

    def __iter__(self):
        return iter([self.tag, self.run_at, self.payload])
