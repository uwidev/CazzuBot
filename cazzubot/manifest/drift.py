"""Warn-only boot-time manifest drift check (roles + channels share it).

Enforcement is manual (the CLIs); this plugin base only reports manifest
drift in the boot logs, mirroring the ``verify_schema`` philosophy without
ever auto-applying. Subclasses supply the domain wiring — ``name``,
``domain`` (the settings prefix and log word), ``default_path``, ``parse``
and a ``_build_plan`` hook — while the read/parse/check/log lifecycle is
shared, so the two domains' drift policy can't drift apart.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import hikari
from typing_extensions import override

from cazzubot import Plugin
from cazzubot.manifest.lines import ManifestError

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)


class ManifestDriftPlugin(Plugin):
    """Warn-only boot drift-check for one manifest domain."""

    _bot: "CazzuBot | None" = None
    # subclass wiring: settings prefix + log word ("roles" / "channels"),
    # the default manifest path, and the domain's parser
    domain: ClassVar[str] = ""
    default_path: ClassVar[str] = ""
    parse: ClassVar[Any] = None

    @override
    async def on_load(self, bot: "CazzuBot") -> None:
        self._bot = bot
        # the guild dump lands after StartedEvent; run the drift check when
        # the configured guild actually becomes available
        bot.subscribe(hikari.GuildAvailableEvent, self._check_once)

    @override
    async def on_unload(self, bot: "CazzuBot") -> None:
        bot.unsubscribe(hikari.GuildAvailableEvent, self._check_once)

    async def _check_once(self, event: hikari.GuildAvailableEvent) -> None:
        bot = self._bot
        if bot is None:
            return
        if event.guild_id != bot.config.guild_id:
            return
        raw = await bot.settings.get(
            f"{self.domain}.manifest.path", self.default_path
        )
        path = Path(str(raw))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            _log.info(
                "%s manifest %s not found — skipping drift check",
                self.domain,
                path,
            )
            return
        try:
            manifest = self.parse(text)
        except ManifestError as err:
            _log.warning(
                "%s manifest invalid (%s):\n%s",
                self.domain,
                path,
                "\n".join(str(issue) for issue in err.issues),
            )
            return

        guild = bot.guild
        if guild is None:
            _log.warning(
                "%s manifest: guild not available yet", self.domain
            )
            return
        plan = await self._build_plan(bot, manifest)
        if plan.is_clean():
            if plan.strays:
                _log.info(
                    "%s manifest ok (%d unmanaged strays — on the"
                    " guild but not in the manifest; kept as-is)",
                    self.domain,
                    len(plan.strays),
                )
            else:
                _log.info("%s manifest ok", self.domain)
        else:
            _log.warning(
                "%s manifest drift — %s\n%s",
                self.domain,
                plan.summary(),
                plan.render(),
            )

    async def _build_plan(self, bot: "CazzuBot", manifest: Any) -> Any:
        """Snapshot the live guild and build the diff plan (domain-specific)."""
        raise NotImplementedError
