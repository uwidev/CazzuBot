"""Roles plugin — warn-only boot-time drift check for the role manifest.

Enforcement is manual (the CLI: ``uv run python -m cazzubot.roles``); this
plugin only reports manifest drift in the boot logs, mirroring the
``verify_schema`` philosophy without ever auto-applying.

Setting: ``roles.manifest.path`` (default ``roles.manifest``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import hikari
from typing_extensions import override

from cazzubot import Plugin
from cazzubot.roles import executor
from cazzubot.roles.parser import ManifestError, parse
from cazzubot.roles.plan import build_plan

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)


class RolesPlugin(Plugin):
    name = "roles"
    _bot: "CazzuBot | None" = None

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
            "roles.manifest.path", "roles.manifest"
        )
        path = Path(str(raw))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            _log.info(
                "roles manifest %s not found — skipping drift check", path
            )
            return
        try:
            manifest = parse(text)
        except ManifestError as err:
            _log.warning(
                "roles manifest invalid (%s):\n%s",
                path,
                "\n".join(str(issue) for issue in err.issues),
            )
            return

        guild = bot.guild
        if guild is None:
            _log.warning("roles manifest: guild not available yet")
            return
        roles = await executor.snapshot_guild(bot.rest, guild.id)
        bot_top_role_id = await executor.bot_top_role_id(
            bot.rest, guild.id
        )
        plan = build_plan(
            manifest,
            roles,
            bot_top_role_id=bot_top_role_id,
        )
        if plan.is_clean():
            if plan.strays:
                _log.info(
                    "roles manifest ok (%d unmanaged strays)",
                    len(plan.strays),
                )
            else:
                _log.info("roles manifest ok")
        else:
            _log.warning(
                "roles manifest drift — %s\n%s",
                plan.summary(),
                plan.render(),
            )


plugin = RolesPlugin()
