"""Asyncio-aware Middlware."""
from aiotinydb.middleware import AIOMiddlewareMixin
from tinydb_serialization import SerializationMiddleware


class AIOSerializationMiddleware(SerializationMiddleware, AIOMiddlewareMixin):
    pass
