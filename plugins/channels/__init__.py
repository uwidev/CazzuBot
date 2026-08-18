"""Channels plugin — warn-only boot-time drift check for the manifest.

Enforcement is manual (the CLI: ``uv run python -m cazzubot.channels``);
the check itself lives in ``cazzubot.manifest.drift``, this module wires
the channels domain.

Setting: ``channels.manifest.path`` (default ``channels.manifest``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cazzubot.channels import executor
from cazzubot.channels.parser import Manifest, parse
from cazzubot.channels.plan import build_plan
from cazzubot.manifest.drift import ManifestDriftPlugin

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot


class ChannelsPlugin(ManifestDriftPlugin):
    """Channels plugin — warn-only boot drift check for the channels manifest."""

    name = "channels"
    domain = "channels"
    default_path = "channels.manifest"
    parse = parse

    async def _build_plan(
        self, bot: "CazzuBot", manifest: Manifest
    ) -> Any:
        guild = bot.guild
        assert guild is not None  # _check_once verifies it first
        channels = await executor.snapshot_guild(bot.rest, guild.id)
        return build_plan(manifest, channels)


plugin = ChannelsPlugin()
