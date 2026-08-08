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
        # the guild is not available until on_ready; hook it there
        bot.add_listener(self._check_once, "on_ready")

    @override
    async def on_unload(self, bot: "CazzuBot") -> None:
        bot.remove_listener(self._check_once, "on_ready")

    async def _check_once(self) -> None:
        bot = self._bot
        if bot is None:
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
        roles = await executor.snapshot_guild(guild)
        plan = build_plan(
            manifest,
            roles,
            bot_top_role_id=guild.me.top_role.id,
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
