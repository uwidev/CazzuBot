"""Holds all data required for certain tasks to execute.

A task is an execution of something meant to occur in the future. We store a database
that holds a payload of information that a module will use to execute its task. Modules
are to implement their own logic; this module is meant to be an interface and manager.

Will work with the database to keep tasks persistent.
"""
from typing import List

from tinydb import TinyDB, where

import src.db_interface as dbi


class TaskEntry:
    def __init__(self, module: str):
        self.module = module


async def add_task(db: TinyDB, task: TaskEntry):
    """Add a task to the ongoing todo dict."""
    await dbi.insert_document(db, "TASK", task)


async def get_tasks(db: TinyDB) -> List[dict]:
    """Return a list of tasks."""
    return await dbi.search(db, "TASK", where("module") == "MODLOG")
