"""Defines schema for databases for autocomplete."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class SnowflakeSchema(ABC):
    @abstractmethod
    def dump(self):
        """Overwrite to return ordered values to write to db."""

    @abstractmethod
    def conflicts(self) -> str:
        """Overwrite to return conflicts to watch out for."""

    def upsert(self) -> str:
        """Return a generic upsert helper string."""
        pairs = []
        for k, v in zip(self.__dict__.keys(), self.__dict__.keys()):
            pairs.append(f"{k} = EXCLUDED.{v}")
        return ", ".join(pairs)


@dataclass
class GuildSettings(SnowflakeSchema):
    gid: int
    mute_role: int

    def dump(self) -> str:
        return f"({self.gid}, {self.mute_role})".replace("None", "NULL")

    def conflicts(self) -> str:
        return "(gid)"
