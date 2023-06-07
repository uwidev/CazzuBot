"""
Manages the database.

All calls must explicitly state what table to call to.

The primary key is the document ID, which is mapped to the guild/user id. This
speeds up lookup times slightly, but has yet to actually be measured.

TinyDB Reference: https://tinydb.readthedocs.io/en/latest/index.html
"""
import logging
from enum import Enum

from tinydb import TinyDB, Query
from tinydb.table import Document

from utility import _log, ReadOnlyDict, update_dict


GUILD_TEMPLATE_SETTINGS = ReadOnlyDict({
    'guild': {},
    'frogs': {}
})


GUILD_TEMPLATE_MODLOGS = ReadOnlyDict({
    
})


USER_TEMPLATE_EXPERIENCE = ReadOnlyDict({
    'experience': 0,
})


class Table(Enum):
    """Enum mapping from database name to their expected schema."""
    GUILD_SETTINGS  = GUILD_TEMPLATE_SETTINGS
    GUILD_MODLOGS   = GUILD_TEMPLATE_MODLOGS
    USER_EXPERIENCE = USER_TEMPLATE_EXPERIENCE


_log = logging.getLogger(__name__)


def valid_table(func):
    """Decorator to ensure table is valid."""
    def check(db: TinyDB, table: Table, id_: int, *args, **kwargs):
        if not table in Table:
            raise Invalidtable(table)

        return func(db, table, id_, *args, **kwargs)

    return check


@valid_table
def insert(db: TinyDB, table: Table, id_: int):
    """Inserts a new templated entry into the table."""
    db_table = db.table(table.name)
    template = dict(table.value)
    db_table.insert(Document(template, id_))


@valid_table
def initialize(db: TinyDB, table: Table, id_: int):
    """Deletes an existing entry and inserts a templated version."""
    template = dict(table.value)

    db_table = db.table(table.name)
    db_table.remove(doc_ids=[id_])
    db_table.insert(Document(template, id_))


def upgrade(db: TinyDB):
    """Converts ALL table entries to new templates.
    
    It does this by removing the entry, creating an updated entry, then
    re-enters it. It will retain any pre-existing values, delete deprecated 
    fields, and add new fields with default values.
    """
    for table in Table:
        db_table = db.table(table.name)
        for entry in iter(db_table):
            upgraded = update_dict(entry, dict(table.value), {})
            db_table.remove(doc_ids=[entry.doc_id])
            db_table.insert(Document(upgraded, entry.doc_id))


def get(db: TinyDB, table: Table, id_: int):
    """Returns the guild's .
    
    If the guild does not exist, raise exception.
    """
    return db.table(table.name).get(doc_id=id_)


class Invalidtable(Exception):
    def __init__(self, table: Table):
        msg = f'Tried inserting data into nonexistant table {table.name}!'
        super().__init__(msg)


class UniqueIdEnforced(Exception):
    def __init__(self, table: Table, id: int):
        msg = (f'This operation on table {table.name} with id {id} only '
               f'allows unique id\'s!')
        super().__init__(msg)


class NotRegistered(Exception):
    def __init__(self, table: Table, id: int):
        msg = (f'id {id} does not exist in table {table.name}!')
        super().__init__(msg)