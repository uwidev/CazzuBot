"""Helper management and typing for modlog entry."""
from aiotinydb import AIOTinyDB
from tinydb import where
from tinydb.table import Document

import src.db_interface as dbi
from src.db_interface import Table
from src.db_templates import ModLogEntry


TEMPLATE = {  # Expected schema for modlogs
    "uid": None,
    "gid": None,
    "cid": None,
    "log_level": None,
    "given_on": None,
    "expires_on": None,
    "reason": None,
    "status": 0,
}


async def add(db: AIOTinyDB, modlog: ModLogEntry):
    await dbi.insert(db, Table.MODLOG, modlog)


async def get_modlogs(db: AIOTinyDB, gid: int) -> list[Document]:
    """Return modlogs for a specific guild."""
    return await dbi.search(db, Table.MODLOG, where("gid") == gid)


async def get_unique_id(db: AIOTinyDB, gid: int):
    """Return the next unique case id."""
    modlogs = await get_modlogs(db, gid)
    if not modlogs:
        return 1

    return sorted(log["cid"] for log in modlogs)[-1] + 1
