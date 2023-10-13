"""Database schema and interactions for PostgreSQL.

These representations are not the same as discord.py. Rather, they are only what the bot
needs to define in order to operate.
"""
from . import (  # noqa: F401
    guild,
    internal,
    member,
    member_exp_log,
    modlog,
    rank,
    table,
    task,
    user,
)
