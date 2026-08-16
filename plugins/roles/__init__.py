"""Roles plugin — warn-only boot-time drift check for the role manifest.

Enforcement is manual (the CLI: ``uv run python -m cazzubot.roles``); the
check itself lives in ``cazzubot.manifest.drift``, this module wires the
roles domain.

Setting: ``roles.manifest.path`` (default ``roles.manifest``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cazzubot.manifest.drift import ManifestDriftPlugin
from cazzubot.roles import executor
from cazzubot.roles.parser import Manifest, parse
from cazzubot.roles.plan import build_plan

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot


class RolesPlugin(ManifestDriftPlugin):
    name = "roles"
    domain = "roles"
    default_path = "roles.manifest"
    parse = parse

    async def _build_plan(
        self, bot: "CazzuBot", manifest: Manifest
    ) -> Any:
        guild = bot.guild
        assert guild is not None  # _check_once verifies it first
        roles = await executor.snapshot_guild(bot.rest, guild.id)
        bot_top_role_id = await executor.bot_top_role_id(
            bot.rest, guild.id
        )
        return build_plan(
            manifest,
            roles,
            bot_top_role_id=bot_top_role_id,
        )


plugin = RolesPlugin()
