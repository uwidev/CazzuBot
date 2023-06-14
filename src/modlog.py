"""Helper management and typing for modlog entry."""
from aiotinydb import AIOTinyDB

import src.db_interface as dbi
from src.db_templates import ModLogEntry


TABLE_NAME = "MODLOG"
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


async def add_modlog(db: AIOTinyDB, modlog: ModLogEntry):
    await dbi.insert_document(db, "MODLOG", modlog)


async def get_next_log_id(db: AIOTinyDB, gid: int):
    modlogs = await dbi.get_guild_modlog(db, gid)
    if not modlogs:
        return 1

    return sorted(log["cid"] for log in modlogs)[-1] + 1
