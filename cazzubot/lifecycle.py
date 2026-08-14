"""Plugin lifecycle — the runtime tracks every effect's undo.

The paper's *revertible effects*, minimal form (level-1 trust): a plugin
declares the undo of each effect **at the point of application** (during
``on_load`` or via ``load_plugin``'s auto-deferrals), and unload replays
those undos **in reverse order** — so teardown is structural (the runtime
knows what to undo) instead of a hand-written ``on_unload`` the author
must remember to write correctly.

Scope (pinned in docs/PLUGIN_ARCHITECTURE.md): the lifecycle recovers
**composition state** — what's active (scheduler rows, subscriptions,
extensions, listeners). It never touches **durable data**: tables and
user rows survive unload by design ("tasks are projections; state is the
source of truth" — pending work is re-armed from state on the next load).

Call graph: ``load_plugin`` defers framework-level effects (scheduler
tags, extensions); plugins call ``bot.lifecycle.defer`` for custom
effects during ``on_load``; ``unload_plugin`` calls ``withdraw`` before
running ``on_unload``. Tests drive ``defer``/``withdraw`` directly.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)

# An undo may be async or sync; both are awaited where applicable.
Undo = Callable[[], Awaitable[None] | None]


class Lifecycle:
    """Per-plugin undo stacks — deferred effects, replayed in reverse.

    A failed undo is logged and swallowed so one bad undo never stops the
    rest of the withdrawal (the cascade keeps going).
    """

    def __init__(self, bot: "CazzuBot") -> None:
        self.bot = bot
        self._undo: dict[str, list[Undo]] = {}

    def defer(self, plugin: str, undo: Undo) -> None:
        """Record ``undo`` as the inverse of an effect just applied.

        Called at the point of application — next to where the effect
        happens — so creation and disposal stay co-located.
        """
        self._undo.setdefault(plugin, []).append(undo)

    async def withdraw(self, plugin: str) -> list[BaseException]:
        """Replay every deferred undo in reverse order; return failures.

        Each undo is awaited; a raising undo is logged and skipped (the
        cascade continues), and the failures are returned so the caller
        can report them.
        """
        failures: list[BaseException] = []
        undos = self._undo.pop(plugin, [])
        for undo in reversed(undos):
            try:
                result = undo()
                if inspect.isawaitable(result):
                    await result
            except Exception as err:  # noqa: BLE001 — isolate per undo
                _log.exception("undo for plugin %s failed", plugin)
                failures.append(err)
        return failures

    def pending(self, plugin: str) -> int:
        """How many undos a plugin has deferred (diagnostics/tests)."""
        return len(self._undo.get(plugin, []))
