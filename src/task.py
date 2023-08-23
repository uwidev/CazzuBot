"""Holds all data required for certain tasks to execute.

A task is an execution of something meant to occur in the future.

Modules are meant to implement their own handling of tasks. Task manager

We store a table in the database that holds a payload of information that a module will
use to execute its task.

Modules are to implement their own logic; this module is meant to be an interface and
manager.

Will work with the database to keep tasks persistent.

TODO: Rewrite this docstring...
"""
import psycopg2.extensions
from aiotinydb import AIOTinyDB
from tinydb import where
from tinydb.table import Document

import src.db_interface as dbi
from src.db_interface import Table
from src.db_templates import TaskEntry


async def add(db: psycopg2.extensions.connection, task: TaskEntry):
    """Add a task to the ongoing todo dict."""
    await dbi._insert(db, Table.TASK, task)


async def all(db: psycopg2.extensions.connection) -> list[Document]:
    """Return tasks."""
    return await dbi.all(db, Table.TASK)


async def tag(db: psycopg2.extensions.connection, module: str) -> list[Document]:
    """Return tasks for a specific module."""
    return await dbi.get_tasks(db, "modlog")
