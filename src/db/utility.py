"""Utility functions for all database operations."""

import logging
from collections.abc import Callable


_log = logging.getLogger(__name__)


def retry(*, on_none: Callable):
    """Decorate a function such that if returns None, will retry and return result.

    Callables will be called with arguments of the decorated function. At times, an
    excessive amount of positional arguments will be passed. Make sure your callable
    consumes those excess with *_.
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            res = await func(*args, **kwargs)
            if res:
                return res

            await on_none(*args, **kwargs)
            return await func(*args, **kwargs)

        return wrapper

    return decorator
