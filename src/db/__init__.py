"""Database schema and interactions for PostgreSQL.

These representations are not the same as discord.py. Rather, they are only what the bot
needs to define in order to operate.
"""

from . import (  # noqa: F401
    channel,
    frog,
    frog_spawn,
    guild,
    internal,
    level,
    member,
    member_exp,
    member_exp_log,
    member_frog,
    member_frog_log,
    modlog,
    rank,
    rank_threshold,
    table,
    task,
    user,
    welcome,
)
