'''
Manages the database related to guilds
Must explicitly interface with the "guild" table.
TinyDB Reference: https://tinydb.readthedocs.io/en/latest/index.html
'''
import logging

import discord
from discord.ext import commands
from tinydb import TinyDB, Query

from utility import _log, ReadOnlyDict, update_dict


_log = logging.getLogger(__name__)


GUILD_TEMPLATE = ReadOnlyDict({
    'id': None,
    'settings': {
        'guild': {},
        'frog': {
            'interval': {}
        },
    },
})


def table_guild(func):
    """Decorator that scopes the database to the guild table."""
    def set_table(*args, **kwargs):
        db = args[0].table('guild')
        return func(db, args[1])

    return set_table


@table_guild
def insert_guild(db: TinyDB, gid: int):
    if db.contains(Query().id == gid):
        _log.warning('Tried to insert gid %d into guild table, '
                    'but already exists!', gid)
        return

    guild = dict(GUILD_TEMPLATE)
    guild['id'] = gid
    db.insert(guild)


@table_guild
def initialize(db: TinyDB, gid: int):
    """Deletes the entire guild data and inserts a fresh entry."""
    old = Query().id == gid
    if not db.contains(old):
        _log.warning('Tried to initialize gid %d into guild table, '
                    'but guild does not exist!', gid)
        return

    new = dict(GUILD_TEMPLATE)
    new['id'] = gid

    db.remove(old)
    db.insert(new)


@table_guild
def upgrade(db: TinyDB, gid: int):
    """Converts all old guild table entries to GUILD_TEMPLATE.
    
    It will retain any pre-existing values, delete deprecated fields,
    and add new fields with default values.
    """
    for guild in iter(db):
        upgraded = update_dict(guild, dict(GUILD_TEMPLATE))
        db.update(upgraded, doc_ids=[guild.doc_id])


@table_guild
def fetch(db: TinyDB, gid: int):
    """Fetches all data for a given guild.
    
    If the guild does not exist, raise exception.
    """
    res = db.get(Query().id == gid)
    if not res:
        raise GuildNotRegistered(gid)

    return res


class GuildNotRegistered(Exception):
    def __init__(self, gid: int):
        msg = f'Tried fetching guild id {gid}. Does not exist!'
        super().__init__(msg)
