"""Channels plugin — warn-only boot-time drift check for the manifest.

Enforcement is manual (the CLI: ``uv run python -m cazzubot.channels``);
this plugin only reports manifest drift in the boot logs, mirroring the
``verify_schema`` philosophy without ever auto-applying.

Setting: ``channels.manifest.path`` (default ``channels.manifest``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import hikari
from typing_extensions import override

from cazzubot import Plugin
from cazzubot.channels import executor
from cazzubot.channels.parser import ManifestError, parse
from cazzubot.channels.plan import build_plan

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)


def _channel_like(ch: hikari.GuildChannel) -> SimpleNamespace:
    """Adapt a hikari channel to the surface ``executor.snapshot_channels`` reads."""
    ns = SimpleNamespace(
        id=ch.id,
        name=ch.name,
        type=ch.type,
        category_id=ch.parent_id,
        position=getattr(ch, "position", 0),
        nsfw=bool(getattr(ch, "is_nsfw", False)),
        slowmode_delay=0,
        default_thread_slowmode_delay=0,
        bitrate=0,
        user_limit=0,
        rtc_region=None,
        video_quality_mode=None,
    )
    if isinstance(ch, hikari.GuildTextChannel):
        ns.slowmode_delay = int(getattr(ch, "rate_limit_per_user", 0) or 0)
    if isinstance(ch, hikari.GuildVoiceChannel):
        ns.bitrate = int(getattr(ch, "bitrate", 0) or 0) // 1000
        ns.user_limit = int(getattr(ch, "user_limit", 0) or 0)
        ns.video_quality_mode = getattr(ch, "video_quality_mode", None)
    return ns


class ChannelsPlugin(Plugin):
    name = "channels"
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
            "channels.manifest.path", "channels.manifest"
        )
        path = Path(str(raw))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            _log.info(
                "channels manifest %s not found — skipping drift check",
                path,
            )
            return
        try:
            manifest = parse(text)
        except ManifestError as err:
            _log.warning(
                "channels manifest invalid (%s):\n%s",
                path,
                "\n".join(str(issue) for issue in err.issues),
            )
            return

        guild = bot.guild
        if guild is None:
            _log.warning("channels manifest: guild not available yet")
            return
        channels = [
            _channel_like(ch)
            for ch in await bot.rest.fetch_guild_channels(guild.id)
        ]
        plan = build_plan(manifest, executor.snapshot_channels(channels))
        if plan.is_clean():
            if plan.strays:
                _log.info(
                    "channels manifest ok (%d unmanaged strays)",
                    len(plan.strays),
                )
            else:
                _log.info("channels manifest ok")
        else:
            _log.warning(
                "channels manifest drift — %s\n%s",
                plan.summary(),
                plan.render(),
            )


plugin = ChannelsPlugin()
