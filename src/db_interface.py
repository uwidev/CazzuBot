"""Defines primative low-level calls to the database.

All calls must explicitly state what table to call to.

TinyDB Reference: https://tinydb.readthedocs.io/en/latest/index.html
"""
import logging
from enum import Enum, auto

from aiotinydb import AIOTinyDB
from tinydb import Query
from tinydb.table import Document

# from src.db_templates import GuildSetting
from src.utility import update_dict


_log = logging.getLogger(__name__)


class Table(Enum):
    TASK = auto()
    MODLOG = auto()
    GUILD_SETTING = auto()


def verify_table(func):
    """Decorate to check to make sure table is a valid Enum table."""

    def check(db, table, *args, **kwargs):
        if not isinstance(table, Table):
            msg = f"table must be of type {Table}, not {type(table)}"
            raise TypeError(msg)
        return func(db, table, *args, **kwargs)

    return check


@verify_table
async def insert(db: AIOTinyDB, table: Table, data: dict, id_: int = None) -> Document:
    """Insert onto the table an entry with doc id as id_."""
    async with db:
        db_table = db.table(table.name)

        if id_:
            db_table.insert(Document(data, id_))
        else:
            db_table.insert(data)


@verify_table
async def upsert(db: AIOTinyDB, table: Table, data: dict, query: Query) -> list[int]:
    async with db:
        db_table = db.table(table.name)
        return db_table.upsert(data, query)


@verify_table
async def get_by_id(db: AIOTinyDB, table: str, id_: int) -> Document:
    """Return document given the table and id."""
    async with db:
        return db.table(table).get(doc_id=id_)


@verify_table
async def search(db: AIOTinyDB, table: str, query: Query):
    """Return documents from table given query."""
    async with db:
        db_table = db.table(table.name)

        return db_table.search(query)


@verify_table
async def get(
    db: AIOTinyDB,
    table: str,
    query: Query = None,
    _id: int = None,
    _ids: list[int] = None,
):
    """Return document from the table given query OR _id OR _ids."""
    if len(list(filter(lambda i: i, [query, _id, _ids]))) > 1:
        raise InvalidQueryError(query, _id, _ids)

    async with db:
        db_table = db.table(table.name)

        return db_table.get(query, _id, _ids)


@verify_table
async def all(db: AIOTinyDB, table: str):
    """Return all documents given a table."""
    async with db:
        return db.table(table).all()


# @verify_table
# async def initialize(db: AIOTinyDB, table: Table, gid: int):
#     """Delete the table matching the id and insert from template."""
#     async with db:
#         db_table = db.table(table)
#         for name, default in GuildSetting.defaults.items():
#             doc = db_table.get((where("name") == name) & (where("gid") == gid))
#             doc.update(default)
#             db_table.update(doc)


def migrate(db: AIOTinyDB):
    """Migrate outdated schema to new schema.

    It does this by removing the document, creating an updated document, then
    re-enters it. It will retain any pre-existing values, delete deprecated
    fields, and add new fields with default values.
    """
    for table in Table:
        db_table = db.table(table.name)
        for doc in iter(db_table):
            upgraded = update_dict(doc, dict(table.value))
            db_table.remove(doc_ids=[doc.doc_id])
            db_table.insert(Document(upgraded, doc.doc_id))


class InvalidtableError(Exception):
    def __init__(self, table: Table):
        msg = f"Tried inserting data into nonexistant table {table.name}!"
        super().__init__(msg)


class UniqueIdEnforcedError(Exception):
    def __init__(self, table: Table, id: int):
        msg = (
            f"This operation on table {table.name} with id {id} only "
            f"allows unique id's!"
        )
        super().__init__(msg)


class NotRegisteredError(Exception):
    def __init__(self, table: Table, id: int):
        msg = f"id {id} does not exist in table {table.name}!"
        super().__init__(msg)


class InvalidQueryError(Exception):
    def __init__(self, query, _id, _ids):
        msg = (
            f"Provided too many arguments when trying to query!\n{query}\n{_id}\n{_ids}"
        )
        super().__init__(msg)
