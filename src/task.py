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
from asyncpg import connection
from tinydb.table import Document

import src.db_interface as dbi
from src.db_interface import Table
from src.db_templates import TaskEntry


async def add(db: connection, task: TaskEntry):
    """Add a task to the ongoing todo dict."""
    await dbi.add_task(db, task)


async def all(db: connection) -> dict:
    """Return all tasks."""
    return await dbi.all(db, Table.TASK)


async def tag(db: connection, module: str) -> dict:
    """Return tasks for a specific module."""
    return await dbi.get_tasks(db, "modlog")
