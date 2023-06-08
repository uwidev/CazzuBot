"""Manages the database.

All calls must explicitly state what table to call to.

The primary key is the document ID, which is mapped to the guild/user id. This
speeds up lookup times slightly, but has yet to actually be measured.

TinyDB Reference: https://tinydb.readthedocs.io/en/latest/index.html
"""
import logging

from tinydb import TinyDB
from tinydb.table import Document

from db_settings_aggregator import Table
from utility import update_dict


_log = logging.getLogger(__name__)


def valid_table(func):
    """Check to see if the table is valid given a database."""

    def check(db: TinyDB, table: Table, id_: int, *args, **kwargs):
        if table not in Table:
            raise InvalidtableError(table)

        return func(db, table, id_, *args, **kwargs)

    return check


@valid_table
def insert(db: TinyDB, table: Table, id_: int):
    """Insert a table into the given database."""
    db_table = db.table(table.name)
    template = dict(table.value)
    db_table.insert(Document(template, id_))


@valid_table
def initialize(db: TinyDB, table: Table, id_: int):
    """Delete the table matching the id and insert from template."""
    template = dict(table.value)

    db_table = db.table(table.name)
    db_table.remove(doc_ids=[id_])
    db_table.insert(Document(template, id_))


def migrate(db: TinyDB):
    """Migrate outdated schema to new schema.

    It does this by removing the document, creating an updated document, then
    re-enters it. It will retain any pre-existing values, delete deprecated
    fields, and add new fields with default values.
    """
    for table in Table:
        db_table = db.table(table.name)
        for doc in iter(db_table):
            upgraded = update_dict(doc, dict(table.value), {})
            db_table.remove(doc_ids=[doc.doc_id])
            db_table.insert(Document(upgraded, doc.doc_id))


def get(db: TinyDB, table: Table, id_: int):
    """Return docuemnt given the table and id.

    If the guild does not exist, raise exception.
    """
    return db.table(table.name).get(doc_id=id_)


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
