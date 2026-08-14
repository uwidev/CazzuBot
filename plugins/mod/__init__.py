"""Mod plugin package."""

import pendulum

from cazzubot import Plugin
from cazzubot.bot import CazzuBot
from typing_extensions import override

from . import db
from .cog import on_modlog_due


class ModPlugin(Plugin):
    name = "mod"
    schema = db.SCHEMA
    extensions = ["plugins.mod.cog"]
    scheduled = {"modlog": on_modlog_due}

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """State-backed scheduling: re-arm pending expiries from the modlog.

        Scheduler rows are **projections** of the modlog (the source of
        truth — ``status='active'`` + ``expires_on``), so a bot restart or
        a plugin unload/reload never loses a mute or tempban expiry. Stale
        projection rows are dropped first (they're rebuilt from state), then
        future deadlines are re-armed and overdue ones applied immediately
        (catch-up); each applied expiry marks its modlog row resolved.
        """
        await bot.scheduler.drop_tag("modlog")
        now = pendulum.now("UTC")
        for log_id, uid, log_type, expires_on in await db.pending_expiries(
            bot.db
        ):
            payload = {
                "uid": uid,
                "log_type": log_type,
                "log_id": log_id,
                "retry": True,
            }
            if expires_on > now:
                await bot.scheduler.add("modlog", expires_on, payload)
            else:
                await on_modlog_due(bot, payload)


plugin = ModPlugin()
