"""Custom serializer for classes to JSON on TinyDB.

Serializes the values within the document, NOT the document itself, as when inserting
into the database, TinyDB checks to see if the document is a Mapping. In other words,
you cannot directly pass a class to write into the database.
"""

from pendulum import DateTime
from tinydb_serialization import Serializer

from src.modlog import ModLogEntry, ModLogStatus, ModLogType


class PDateTimeSerializer(Serializer):
    OBJ_CLASS = DateTime  # The class this serializer handles

    def encode(self, obj: DateTime):
        return obj.isoformat()

    def decode(self, s: str):
        return DateTime.fromisoformat(s)


class ModLogtypeSerializer(Serializer):
    OBJ_CLASS = ModLogType

    def encode(self, obj: ModLogType):
        return obj.value

    def decode(self, s: str):
        return self.OBJ_CLASS(s)


class ModLogStatusSerializer(Serializer):
    OBJ_CLASS = ModLogStatus

    def encode(self, obj: ModLogEntry):
        return str(obj.value)

    def decode(self, s: str):
        return self.OBJ_CLASS(int(s))
