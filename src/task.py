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
from aiotinydb import AIOTinyDB
from tinydb import where
from tinydb.table import Document

import src.db_interface as dbi
from src.db_interface import Table
from src.db_templates import TaskEntry


async def add(db: AIOTinyDB, task: TaskEntry):
    """Add a task to the ongoing todo dict."""
    await dbi.insert(db, Table.TASK, task)


async def all(db: AIOTinyDB) -> list[Document]:
    """Return tasks."""
    return await dbi.all(db, Table.TASK)


async def tag(db: AIOTinyDB, module: str) -> list[Document]:
    """Return tasks for a specific module."""
    return await dbi.search(db, Table.TASK, where("tag") == module)
