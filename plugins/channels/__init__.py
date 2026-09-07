"""Channels plugin — warn-only boot-time drift check for the manifest.

Enforcement is manual (the CLI: ``uv run python -m core.channels``);
the check itself lives in ``core.manifest.drift``, this module wires
the channels domain.

Setting: ``channels.manifest.path`` (default ``channels.manifest``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.channels import executor
from core.channels.parser import Manifest, parse
from core.channels.plan import build_plan
from core.manifest.drift import ManifestDriftPlugin

if TYPE_CHECKING:
    from core.bot import CazzuBot


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
