"""Utility functions for all database operations.

Other modules will need to dependency inject their async functions in order for this
to work properly.
"""

import functools
import logging
from collections.abc import Callable

from asyncpg import ForeignKeyViolationError

from . import table


_log = logging.getLogger(__name__)

# Variables must be set at runtime to a async function which adds the key into the
# table, corrosponding to said table. This is dependency injection and is here to
# prevent circular importing.
insert_cid = None
insert_gid = None
insert_uid = None
insert_member = None


def retry(*, on_none: Callable):
    """Decorate a function such that if returns None, will retry and return result.

    Callables will be called with arguments of the decorated function. At times, an
    excessive amount of positional arguments will be passed. Make sure your callable
    consumes those excess with *_.
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            res = await func(*args, **kwargs)
            if res is not None:
                return res

            await on_none(*args, **kwargs)
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def fkey_gid(original_func):
    """Ensure the gid passed exists on the guild table. If not create it.

    THIS IS A DECORATOR!

    You should only use this when making any changes where a reference to guild is made.
    This includes adding new members, specific guild settings, etc. You shouldn't ever
    need to update the gid value of a row, ever.

    This also requires that the structure of the function is as follows.
        def function(pool, payload)
    where payload is some db.table.SnowflakeTable containing gid.
    """

    @functools.wraps(original_func)
    async def wrapper(*args, **kwargs):

        if not hasattr(args[1], "gid"):
            msg = "Provided payload object does not have attribute gid"
            raise AttributeError(msg)

        try:
            await original_func(*args, **kwargs)

        except ForeignKeyViolationError:
            pool = args[0]
            gid = args[1].gid
            await insert_gid(pool, table.Guild(gid))

            await original_func(*args, **kwargs)

    return wrapper


def fkey_uid(original_func):
    """Ensure the uid passed exists on the user table. If not create it.

    See fkey_gid for more details.

    Function structure is the same, but must have uid instead of gid.
    """

    @functools.wraps(original_func)
    async def wrapper(*args, **kwargs):
        if not hasattr(args[1], "uid"):
            msg = "Provided payload object does not have attribute uid"
            raise AttributeError(msg)

        try:
            await original_func(*args, **kwargs)

        except ForeignKeyViolationError:
            pool = args[0]
            uid = args[1].uid
            await insert_uid(pool, table.User(uid))

            await original_func(*args, **kwargs)

    return wrapper


def fkey_cid(original_func):
    """Ensure the cid passed exists on the channel table. If not create it.

    See fkey_gid for more details.

    Function structure is the same, but must have cid instead of gid.
    """

    @functools.wraps(original_func)
    async def wrapper(*args, **kwargs):
        if not hasattr(args[1], "cid"):
            msg = "Provided payload object does not have attribute cid"
            raise AttributeError(msg)

        try:
            await original_func(*args, **kwargs)

        except ForeignKeyViolationError:
            pool = args[0]
            cid = args[1].cid
            await insert_cid(pool, table.User(cid))

            await original_func(*args, **kwargs)

    return wrapper


def fkey_member(original_func):
    """Ensure the gid, uid passed exists on the member table. If not create it.

    Will also check for gid on guild and uid on user.

    See fkey_gid for more details.

    Function structure is the same, but must have gid and uid.
    """

    @fkey_gid
    @fkey_uid
    @functools.wraps(original_func)
    async def wrapper(*args, **kwargs):
        if not hasattr(args[1], "gid"):
            msg = "Provided payload object does not have attribute gid"
            raise AttributeError(msg)
        if not hasattr(args[1], "uid"):
            msg = "Provided payload object does not have attribute uid"
            raise AttributeError(msg)

        try:
            await original_func(*args, **kwargs)

        except ForeignKeyViolationError:
            pool = args[0]
            gid = args[1].gid
            uid = args[1].uid
            await insert_member(pool, table.Member(gid, uid))

            await original_func(*args, **kwargs)

    return wrapper


def fkey_channel(original_func):
    """Ensure the gid, cid passed exists on the channel table. If not create it.

    Will also check for gid on guild.

    See fkey_gid for more details.

    Function structure is the same, but must have gid and cid.
    """

    @fkey_gid
    @functools.wraps(original_func)
    async def wrapper(*args, **kwargs):
        if not hasattr(args[1], "gid"):
            msg = "Provided payload object does not have attribute gid"
            raise AttributeError(msg)
        if not hasattr(args[1], "cid"):
            msg = "Provided payload object does not have attribute cid"
            raise AttributeError(msg)

        try:
            await original_func(*args, **kwargs)

        except ForeignKeyViolationError:
            pool = args[0]
            gid = args[1].gid
            cid = args[1].cid
            await insert_cid(pool, table.Channel(gid, cid))

            await original_func(*args, **kwargs)

    return wrapper
