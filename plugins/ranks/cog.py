"""Ranks plugin extension — per-window rank threshold management."""

import json
from typing import cast

import hikari
import lightbulb

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot
from cazzubot.models import WindowEnum
from lightbulb.prefab import checks as prefab_checks

from cazzubot.window import window_error, window_success

from . import db as ranks_db
from .logic import formatter

loader = lightbulb.Loader()

_ADMIN = prefab_checks.has_permissions(hikari.Permissions.ADMINISTRATOR)

rank = lightbulb.Group("rank", "Manage ranked roles.")


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


def _mode_option(name: str = "mode", description: str = "The rank window"):
    return lightbulb.string(
        name,
        description,
        default="seasonal",
        choices=[
            lightbulb.Choice("Seasonal", "seasonal"),
            lightbulb.Choice("Lifetime", "lifetime"),
        ],
    )


@rank.register
class Add(
    lightbulb.SlashCommand,
    name="add",
    description="Add a rank role at a level threshold.",
    hooks=[_ADMIN],
):
    level = lightbulb.integer(
        "level", "The level threshold", min_value=1, max_value=999
    )
    role = lightbulb.role("role", "The rank role")
    mode = _mode_option()

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await ranks_db.add(
            bot.db, self.role.id, self.level, mode=WindowEnum(self.mode)
        )
        await window_success(
            ctx, f"Added {self.role} at level {self.level}"
        )


@rank.register
class Remove(
    lightbulb.SlashCommand,
    name="remove",
    description="Remove a rank role.",
    hooks=[_ADMIN],
):
    role = lightbulb.role("role", "The rank role")
    mode = _mode_option()

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await ranks_db.delete(bot.db, self.role.id, WindowEnum(self.mode))
        await window_success(ctx, f"Removed {self.role}")


@rank.register
class Clean(
    lightbulb.SlashCommand,
    name="clean",
    description="Remove ranks whose roles no longer exist in the guild.",
    hooks=[_ADMIN],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        guild = bot.guild
        if guild is None:
            await window_error(
                ctx, "Run rank clean in the server, not DMs."
            )
            return
        rows = [
            *await ranks_db.get(bot.db, mode=WindowEnum.SEASONAL),
            *await ranks_db.get(bot.db, mode=WindowEnum.LIFETIME),
        ]
        removed = {r.rid for r in rows if not bot.cache.get_role(r.rid)}
        await ranks_db.batch_delete(bot.db, list(removed))
        await window_success(
            ctx, f"Removed {len(removed)} stale rank roles"
        )


@rank.register
class Clear(
    lightbulb.SlashCommand,
    name="clear",
    description="Drop all rank thresholds for a window.",
    hooks=[_ADMIN],
):
    mode = _mode_option()

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await ranks_db.drop(bot.db, WindowEnum(self.mode))
        await window_success(ctx, "Cleared rank thresholds")


rank_set = rank.subgroup("set", "Configure rank settings.")


@rank_set.register
class SetEnabled(
    lightbulb.SlashCommand,
    name="enabled",
    description="Enable or disable rank-up messages for a window.",
    hooks=[_ADMIN],
):
    val = lightbulb.boolean("val", "Whether rank messages are enabled")
    mode = _mode_option()

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await ranks_db.set_enabled(
            bot.settings, self.val, WindowEnum(self.mode)
        )
        await window_success(
            ctx,
            "Rank messages enabled"
            if self.val
            else "Rank messages disabled",
        )


@rank_set.register
class SetKeepOld(
    lightbulb.SlashCommand,
    name="keep_old",
    description="Keep old rank roles after a reset for a window.",
    hooks=[_ADMIN],
):
    val = lightbulb.boolean("val", "Whether to keep old rank roles")
    mode = _mode_option()

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await ranks_db.set_keep_old(
            bot.settings, self.val, WindowEnum(self.mode)
        )
        await window_success(ctx, f"Keep-old set to {self.val}")


@rank_set.register
class SetMessage(
    lightbulb.SlashCommand,
    name="message",
    description="Set the rank-up message JSON.",
    hooks=[_ADMIN],
):
    message = lightbulb.string("message", "The rank-up message JSON")
    mode = _mode_option()

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Set the rank-up message JSON for a window."""
        bot = _bot(ctx)
        decoded = templates.verify(
            self.message,
            formatter,
            member=utils.member_snapshot(ctx.member or ctx.user),
        )
        await ranks_db.set_message(
            bot.settings, decoded, WindowEnum(self.mode)
        )
        await window_success(ctx, "Rank message set")


@rank.register
class Demo(
    lightbulb.SlashCommand,
    name="demo",
    description="Preview the rank-up message.",
    hooks=[_ADMIN],
):
    mode = _mode_option()

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        msg_json = await ranks_db.get_message(
            bot.settings, WindowEnum(self.mode)
        )
        if not msg_json:
            await ctx.respond("No rank-up message has been set.")
            return
        utils.deep_map(
            msg_json,
            formatter,
            member=utils.member_snapshot(ctx.member or ctx.user),
        )
        await templates.send(ctx, msg_json)


@rank.register
class Raw(
    lightbulb.SlashCommand,
    name="raw",
    description="Dump the raw stored rank-up message JSON.",
    hooks=[_ADMIN],
):
    mode = _mode_option()

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        msg_json = await ranks_db.get_message(
            bot.settings, WindowEnum(self.mode)
        )
        await ctx.respond(f"```{json.dumps(msg_json, indent=2)}```")


loader.command(rank)
