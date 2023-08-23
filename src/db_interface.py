"""Handles direct interactions with the database.

No other place should require the programmer to write SQL code. This module acts as
the middleman, the API, w/e, to the database.
"""
import logging
from enum import Enum, auto

import psycopg2.extensions

from src.db_schema import SnowflakeSchema
from src.utility import update_dict


_log = logging.getLogger(__name__)


class Table(Enum):
    TASK = "task"
    MODLOG = "modlog"
    GUILD_SETTING = "guild_setting"


async def get_tasks(db: psycopg2.extensions.connection, module: str):
    """Fetch all tasks that match the module."""
    return await _select(db, Table.TASK, "*", f"'{module}' = ANY(tag)")


async def set_mute_role(db, gid: int, role: int):
    """Set the mute role on guild settings."""
    return await _update(db, Table.GUILD_SETTING, f"mute_role = {role}", f"gid = {gid}")


async def initialize_guild(db, gid: int, defaults: dict):
    """Insert a new entry into guild settings with default values."""


def verify_table(func):
    """Decorate to check to make sure table is a valid table from defined enum."""

    def check(db, table, *args, **kwargs):
        if not isinstance(table, Table):
            msg = f"table must be of type {Table}, not {type(table)}"
            raise TypeError(msg)
        return func(db, table, *args, **kwargs)

    return check


@verify_table
async def _insert(
    db: psycopg2.extensions.connection, table: Table, data: SnowflakeSchema
):
    """Write generic data insertion onto any table depending on its schema."""
    with db.cursor() as curs:
        try:
            curs.execute(
                f"""
                INSERT INTO {table.value}
                VALUES {data.dump()}
                """
            )
        except psycopg2.DatabaseError as err:
            _log.warning(err)
            db.rollback()
        else:
            db.commit()


@verify_table
async def _upsert(
    db: psycopg2.extensions.connection, table: Table, data: SnowflakeSchema
):
    """Upsert generic data into table given a proper schema."""
    with db.cursor() as curs:
        try:
            curs.execute(
                f"""
                INSERT INTO {table.value}
                VALUES {data.dump()}
                ON CONFLICT {data.conflicts()}
                DO UPDATE SET {data.upsert()}
                """
            )
        except psycopg2.DatabaseError as err:
            _log.warning(err)
            db.rollback()
        else:
            db.commit()


@verify_table
async def _select(
    db: psycopg2.extensions.connection, table: str, columns: str, query: str
):
    """Select genericly from a table given a SQL-compatible condition string."""
    with db.cursor() as curs:
        try:
            curs.execute(
                f"""
                SELECT {columns}
                FROM {table.value}
                WHERE {query}
                """
            )

            data = curs.fetchall()
        except psycopg2.DatabaseError as err:
            _log.warn(err)

    return data


@verify_table
async def _update(
    db: psycopg2.extensions.connection, table: Table, val: str, cond: str
):
    """Write generic data insertion onto any table depending on its schema."""
    with db.cursor() as curs:
        try:
            curs.execute(
                f"""
                UPDATE {table.value}
                SET {val}
                WHERE {cond}
                """
            )
        except psycopg2.DatabaseError as err:
            _log.warning(err)
            db.rollback()
        else:
            db.commit()


# @verify_table
# async def get(
#     db: AIOTinyDB,
#     table: str,
#     query: Query = None,
#     _id: int = None,
#     _ids: list[int] = None,
# ):
#     """Return document from the table given query OR _id OR _ids."""
#     if len(list(filter(lambda i: i, [query, _id, _ids]))) > 1:
#         raise InvalidQueryError(query, _id, _ids)

#     async with db:
#         db_table = db.table(table.name)

#         return db_table.get(query, _id, _ids)


# @verify_table
# async def all(db: AIOTinyDB, table: str):
#     """Return all documents given a table."""
#     async with db:
#         return db.table(table).all()


# @verify_table
# async def initialize(db: AIOTinyDB, table: Table, gid: int):
#     """Delete the table matching the id and insert from template."""
#     async with db:
#         db_table = db.table(table)
#         for name, default in GuildSetting.defaults.items():
#             doc = db_table.get((where("name") == name) & (where("gid") == gid))
#             doc.update(default)
#             db_table.update(doc)


# async def test_db(db: psycopg2.extensions.connection, gid: int):
#     _log.info("testing database...")

#     with db.cursor() as curs:
#         try:
#             curs.execute(
#                 f"""
#                 INSERT INTO guild_setting
#                 VALUES({gid})
#                 ON CONFLICT (gid)
#                 DO NOTHING
#                 """
#             )
#         except psycopg2.DatabaseError as err:
#             _log.error(err)
#         else:
#             db.commit()


# def migrate(db: AIOTinyDB):
#     """Migrate outdated schema to new schema.

#     It does this by removing the document, creating an updated document, then
#     re-enters it. It will retain any pre-existing values, delete deprecated
#     fields, and add new fields with default values.
#     """
#     for table in Table:
#         db_table = db.table(table.name)
#         for doc in iter(db_table):
#             upgraded = update_dict(doc, dict(table.value))
#             db_table.remove(doc_ids=[doc.doc_id])
#             db_table.insert(Document(upgraded, doc.doc_id))


# class InvalidtableError(Exception):
#     def __init__(self, table: Table):
#         msg = f"Tried inserting data into nonexistant table {table.name}!"
#         super().__init__(msg)


# class UniqueIdEnforcedError(Exception):
#     def __init__(self, table: Table, id: int):
#         msg = (
#             f"This operation on table {table.name} with id {id} only "
#             f"allows unique id's!"
#         )
#         super().__init__(msg)


# class NotRegisteredError(Exception):
#     def __init__(self, table: Table, id: int):
#         msg = f"id {id} does not exist in table {table.name}!"
#         super().__init__(msg)


# class InvalidQueryError(Exception):
#     def __init__(self, query, _id, _ids):
#         msg = (
#             f"Provided too many arguments when trying to query!\n{query}\n{_id}\n{_ids}"
#         )
#         super().__init__(msg)
