"""Ranks plugin cog — per-window rank threshold management."""

import json
from typing import Any

import discord
from discord.ext import commands

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot
from cazzubot.window import window_error, window_success
from cazzubot.models import WindowEnum
from typing_extensions import override

from . import db as ranks_db
from .logic import formatter


class RanksCog(commands.Cog):
    """Ranked roles based on level thresholds."""

    def __init__(self, bot: CazzuBot) -> None:
        self.bot = bot

    @override
    async def cog_check(self, ctx: commands.Context[Any]) -> bool:
        author = ctx.author
        if not isinstance(author, discord.Member):
            return False
        perms = ctx.channel.permissions_for(author)
        return bool(perms.administrator)

    @commands.hybrid_group(name="rank", aliases=["ranks"])
    async def rank(self, _ctx: commands.Context[CazzuBot]) -> None:
        """Manage ranked roles."""

    @rank.command(name="add")
    async def rank_add(
        self,
        ctx: commands.Context[CazzuBot],
        level: int,
        role: discord.Role,
        mode: WindowEnum = WindowEnum.SEASONAL,
    ) -> None:
        """Add a rank role at a level threshold."""
        if not 1 <= level <= 999:
            await ctx.send("Level must be between 1-999.")
            return
        await ranks_db.add(self.bot.db, role.id, level, mode=mode)
        await window_success(ctx, f"Added {role} at level {level}")

    @rank.command(name="remove", aliases=["del"])
    async def rank_remove(
        self,
        ctx: commands.Context[CazzuBot],
        arg: discord.Role,
        mode: WindowEnum = WindowEnum.SEASONAL,
    ) -> None:
        """Remove a rank role."""
        await ranks_db.delete(self.bot.db, arg.id, mode)
        await window_success(ctx, f"Removed {arg}")

    @rank.command(name="clean")
    async def rank_clean(self, ctx: commands.Context[CazzuBot]) -> None:
        """Remove ranks whose roles no longer exist in the guild."""
        rows = await ranks_db.get(self.bot.db)
        guild = ctx.guild
        if guild is None:
            await window_error(
                ctx, "Run rank clean in the server, not DMs."
            )
            return
        removed = [r.rid for r in rows if not guild.get_role(r.rid)]
        await ranks_db.batch_delete(self.bot.db, removed)
        await window_success(
            ctx, f"Removed {len(removed)} stale rank roles"
        )

    @rank.command(name="clear", aliases=["purge", "drop"])
    async def rank_clear(
        self,
        ctx: commands.Context[CazzuBot],
        mode: WindowEnum = WindowEnum.SEASONAL,
    ) -> None:
        """Drop all rank thresholds for a window."""
        await ranks_db.drop(self.bot.db, mode)
        await window_success(ctx, "Cleared rank thresholds")

    @rank.group(name="set")
    async def rank_set(self, _ctx: commands.Context[CazzuBot]) -> None:
        """Configure rank settings."""

    @rank_set.command(name="enabled")
    async def rank_set_enabled(
        self,
        ctx: commands.Context[CazzuBot],
        val: bool,
        mode: WindowEnum = WindowEnum.SEASONAL,
    ) -> None:
        """Enable or disable rank-up messages for a window."""
        await ranks_db.set_enabled(self.bot.settings, val, mode)
        await window_success(
            ctx,
            "Rank messages enabled" if val else "Rank messages disabled",
        )

    @rank_set.command(name="keep_old", aliases=["keepOld"])
    async def rank_set_keep_old(
        self,
        ctx: commands.Context[CazzuBot],
        val: bool,
        mode: WindowEnum = WindowEnum.SEASONAL,
    ) -> None:
        """Keep old rank roles after a reset for a window."""
        await ranks_db.set_keep_old(self.bot.settings, val, mode)
        await window_success(ctx, f"Keep-old set to {val}")

    @rank_set.command(name="message", aliases=["msg"])
    async def rank_set_message(
        self,
        ctx: commands.Context[CazzuBot],
        *,
        message: str,
        mode: WindowEnum = WindowEnum.SEASONAL,
    ) -> None:
        """Set the rank-up message JSON.

        Append a window name ("lifetime"/"seasonal") after the closing brace to
        configure a specific window; otherwise the default argument applies.
        """
        last_closing = len(message) - 1 - message[::-1].find("}")
        tail = message[last_closing + 1 :].strip()
        message = message[: last_closing + 1]
        if tail:
            parsed = _parse_mode(tail)
            if parsed is None:
                raise commands.BadArgument(
                    f"Unable to convert mode {tail} to type WindowEnum"
                )
            mode = parsed

        decoded = templates.verify(
            message, formatter, member=utils.member_snapshot(ctx.author)
        )
        await ranks_db.set_message(self.bot.settings, decoded, mode)
        await window_success(ctx, "Rank message set")

    @rank.command(name="demo")
    async def rank_demo(
        self,
        ctx: commands.Context[CazzuBot],
        mode: WindowEnum = WindowEnum.SEASONAL,
    ) -> None:
        msg_json = await ranks_db.get_message(self.bot.settings, mode)
        if not msg_json:
            await ctx.send("No rank-up message has been set.")
            return
        utils.deep_map(
            msg_json,
            formatter,
            member=utils.member_snapshot(ctx.author),
        )
        await templates.send(ctx, msg_json)

    @rank.command(name="raw")
    async def rank_raw(
        self,
        ctx: commands.Context[CazzuBot],
        mode: WindowEnum = WindowEnum.SEASONAL,
    ) -> None:
        msg_json = await ranks_db.get_message(self.bot.settings, mode)
        await ctx.send(f"```{json.dumps(msg_json, indent=2)}```")


def _parse_mode(raw: str) -> WindowEnum | None:
    try:
        return WindowEnum(raw.strip().lower())
    except ValueError:
        return None
