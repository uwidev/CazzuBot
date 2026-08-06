"""A window into a command's internal state, surfaced to Discord.

Buffered, level-tagged reporting that flushes as a single message so
per-line calls never flood the API. Distinct from CLI ``logging`` (which
stays for bot internals — db, connection, plugin hooks): the window shows
command-local state to the invoker. Levels:

- ``debug`` / ``info`` — plain line
- ``success`` — prefixed ``✓`` (U+2713)
- ``warn`` — prefixed ``⚠︎`` (U+26A0 + U+FE0E, text-rendered)
- ``error`` — prefixed ``✖`` (U+2716)

Context manager::

    async with command_window(ctx) as window:
        window.info("fetching logs...")
        await window.flush()  # only before blocking work
        window.success("done")

Decorator::

    @commands.hybrid_command()
    @windowed
    async def cmd(self, ctx, ...):
        ctx.window.info("...")

One-off::

    await window_success(ctx, "mute role set")
"""

import functools
import logging
from collections.abc import Callable
from types import TracebackType
from typing import Any, Protocol, TypeVar, cast

_log = logging.getLogger(__name__)

_SUCCESS = "\u2713"  # ✓
_WARN = "\u26a0\ufe0e"  # ⚠︎ (text presentation, not emoji)
_ERROR = "\u2716"  # ✖


class Sendable(Protocol):
    """Anything a window can flush to (a command ``ctx`` in practice)."""

    async def send(
        self,
        content: str | None = None,
        *,
        ephemeral: bool = False,
    ) -> Any: ...


class CommandWindow:
    """Buffered level-tagged reporting for one command invocation."""

    def __init__(self, ctx: Sendable) -> None:
        self._ctx = ctx
        self._lines: list[str] = []

    # -- levels -----------------------------------------------------------

    def debug(self, msg: object) -> None:
        self._lines.append(str(msg))

    def info(self, msg: object) -> None:
        self._lines.append(str(msg))

    def success(self, msg: object) -> None:
        self._lines.append(f"{_SUCCESS} {msg}")

    def warn(self, msg: object) -> None:
        self._lines.append(f"{_WARN} {msg}")

    def error(self, msg: object) -> None:
        self._lines.append(f"{_ERROR} {msg}")

    # -- delivery ----------------------------------------------------------

    async def flush(self, *, monospace: bool = False) -> None:
        """Send buffered lines as one message; no-op when empty."""
        if not self._lines:
            return
        text = "\n".join(self._lines)
        if monospace:
            text = f"```\n{text}\n```"
        await self._ctx.send(text, ephemeral=True)
        self._lines = []

    # -- context manager ---------------------------------------------------

    async def __aenter__(self) -> "CommandWindow":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc_type is not None:
            self.error(f"{exc_type.__name__}: {exc}")
        try:
            await self.flush()
        except Exception:
            # never let a failed flush mask the real command outcome
            _log.exception("failed to flush command window")
        return False  # re-raise


def command_window(ctx: Sendable) -> CommandWindow:
    """Open a window into a command's internal state."""
    return CommandWindow(ctx)


F = TypeVar("F", bound=Callable[..., Any])


def windowed(func: F) -> F:
    """Attach a CommandWindow to the command's ``ctx`` as ``ctx.window``.

    Auto-flushes at the end of the command and on error. Stack it below
    ``@commands.hybrid_command()`` / ``@commands.command()`` so the command
    signature (and thus slash-option parsing) is untouched.
    """

    @functools.wraps(func)
    async def wrapper(
        self: Any, ctx: Any, *args: Any, **kwargs: Any
    ) -> Any:
        window = CommandWindow(ctx)
        ctx.window = window
        try:
            result = await func(self, ctx, *args, **kwargs)
        except BaseException as exc:
            window.error(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            try:
                await window.flush()
            except Exception:
                _log.exception("failed to flush command window")
        return result

    return cast(F, wrapper)


async def _one_off(ctx: Sendable, level: str, msg: object) -> None:
    window = CommandWindow(ctx)
    getattr(window, level)(msg)
    await window.flush()


async def window_debug(ctx: Sendable, msg: object) -> None:
    await _one_off(ctx, "debug", msg)


async def window_info(ctx: Sendable, msg: object) -> None:
    await _one_off(ctx, "info", msg)


async def window_success(ctx: Sendable, msg: object) -> None:
    await _one_off(ctx, "success", msg)


async def window_warn(ctx: Sendable, msg: object) -> None:
    await _one_off(ctx, "warn", msg)


async def window_error(ctx: Sendable, msg: object) -> None:
    await _one_off(ctx, "error", msg)
