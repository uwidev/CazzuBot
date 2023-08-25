"""Handles general direct interactions with the database.

For module-specific queries, see other files in src.db

Asyncpg follows native PostgreSQL for query arguments $n. In other words, when writing a
query, you should NOT do a string format on the query. Rather, additional arguments are
given which will be substituted into the string after internal sanitation.
"""
import logging
from enum import Enum

from src.db.schema import GuildSettingsSchema
from src.utility import update_dict


_log = logging.getLogger(__name__)


class Table(Enum):
    TASK = "task"
    MODLOG = "modlog"
    GUILD_SETTING = "guild_setting"


async def set_mute_role(db, gid: int, role: int):
    """Set the mute role on guild settings."""
    async with db.acquire() as con:
        async with con.transaction():
            try:
                await con.execute(
                    """
                    UPDATE guild_setting
                    SET mute_role = ($1)
                    WHERE gid = $2
                    """,
                    role,
                    gid,
                )
            except Exception as err:
                _log.error(err)
                return 1
            else:
                return 0


async def initialize_guild(db, gid: int):
    """Insert a new entry into guild settings with default values."""
    defaults = GuildSettingsSchema(gid)
    async with db.acquire() as con:
        async with con.transaction():
            try:
                await con.execute(
                    """
                    INSERT INTO guild_setting (gid, mute_role)
                    VALUES ($1, $2)
                    """,
                    *defaults,
                )
            except Exception as err:
                _log.error(err)
                return 1
            else:
                return 0


# def verify_table(func):
#     """Decorate to check to make sure table is a valid table from defined enum."""

#     def check(db, table, *args, **kwargs):
#         if not isinstance(table, Table):
#             msg = f"table must be of type {Table}, not {type(table)}"
#             raise TypeError(msg)
#         return func(db, table, *args, **kwargs)

#     return check

# @verify_table
# async def _insert(db: Pool, table: Table, data: SnowflakeSchema) -> int:
#     """Write generic data insertion onto any table depending on its schema."""
#     async with db.acquire() as con:
#         async with con.transaction():
#             try:
#                 await con.execute(
#                     """
#                     INSERT INTO $1 $2
#                     VALUES $3
#                     """,
#                     table.value,
#                     data.columns(),
#                     data.values(),
#                 )
#             except Exception as err:
#                 _log.error(err)
#                 return 1
#             else:
#                 return 0


# @verify_table
# async def _upsert(db: Pool, table: Table, data: SnowflakeSchema) -> int:
#     """Upsert generic data into table given a proper schema."""
#     async with db.acquire() as con:
#         async with con.transaction():
#             try:
#                 await con.execute(
#                     """
#                     INSERT INTO $1 $2
#                     VALUES $3
#                     ON CONFLICT $4
#                     DO UPDATE SET $5
#                     """,
#                     (
#                         table.value,
#                         data.columns(),
#                         data.values(),
#                         data.conflicts(),
#                         data.upsert(),
#                     ),
#                 )
#             except Exception as err:
#                 _log.error(err)
#                 return 1
#             else:
#                 return 0


# @verify_table
# async def _select(db: Pool, table: Table, columns: str, query: str) -> dict:
#     """Select genericly from a table given a SQL-compatible condition string."""
#     async with db.acquire() as con:
#         try:
#             print(f"{columns=}")
#             print(f"{table.value=}")
#             print(f"{query=}")
#             data = await con.fetch(
#                 """
#                 SELECT $1
#                 FROM $2
#                 WHERE $3
#                 """,
#                 columns,
#                 table.value,
#                 query,
#             )
#         except Exception as err:
#             _log.warn(err)
#         else:
#             return data


# @verify_table
# async def _update(db: Pool, table: Table, val: str, cond: str) -> int:
#     """Write generic data insertion onto any table depending on its schema."""
#     async with db.dacquire() as con:
#         try:
#             con.execute(
#                 f"""
#                 UPDATE {table.value}
#                 SET {val}
#                 WHERE {cond}
#                 """
#             )
#         except Exception as err:
#             _log.warning(err)
#             db.rollback()
#             return 1
#         else:
#             db.commit()
#             return 0


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


# async def test_db(db: asyncpg.extensions.Pool, gid: int):
#     _log.info("testing database...")

#     with db.dacquire() as con:
#         try:
#             con.execute(
#                 f"""
#                 INSERT INTO guild_setting
#                 VALUES({gid})
#                 ON CONFLICT (gid)
#                 DO NOTHING
#                 """
#             )
#         except asyncpg.DatabaseError as err:
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
