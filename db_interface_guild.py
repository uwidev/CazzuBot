'''
Manages the database related to guilds
Must explicitly interface with the "guild" table.
TinyDB Reference: https://tinydb.readthedocs.io/en/latest/index.html
'''
import discord
from tinydb import TinyDB, Query

from utility import log, ReadOnlyDict


GUILD_TEMPLATE = ReadOnlyDict({
    'id': None,
    'modlog': dict()
})


def table_guild(func):
    def set_table(*args, **kwargs):
        db = args[0].table('guild')
        return func(db, args[1])

    return set_table

@table_guild
def insert_guild(db: TinyDB, gid: int):
    if db.contains(Query().id == gid):
        log.warning('Tried to insert gid %d into guild table, '
                    'but already exists!', gid)
        return

    guild = dict(GUILD_TEMPLATE)
    guild['id'] = gid
    db.insert(guild)


def initialize(db: TinyDB, gid: int):
    if db.contains(Query().id == gid):
        log.warning('Tried to initialize gid %d into guild table, '
                    'but guild does not exist!', gid)
        return

    new = dict(GUILD_TEMPLATE)
    new['id'] = gid