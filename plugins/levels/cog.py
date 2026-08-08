"""Levels plugin extension — level-up message configuration.

Lightbulb extension module: a module-level ``lightbulb.Loader`` holding the
``level`` command group (admin-only).
"""

import json
from typing import cast

import hikari
import lightbulb

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot
from lightbulb.prefab import checks as prefab_checks

from cazzubot.window import window_success

from .logic import MESSAGE_KEY, formatter

loader = lightbulb.Loader()

level = lightbulb.Group("level", "Configure the level-up message.")


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


@level.register
class Set(
    lightbulb.SlashCommand,
    name="set",
    description="Set the level-up message JSON.",
    hooks=[
        prefab_checks.has_permissions(hikari.Permissions.ADMINISTRATOR)
    ],
):
    message = lightbulb.string("message", "The level-up message JSON")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        member = ctx.member or ctx.user
        decoded = templates.verify(
            self.message,
            formatter,
            member=utils.member_snapshot(member),
        )
        await bot.settings.set(MESSAGE_KEY, decoded)
        await window_success(ctx, "Level-up message set")


@level.register
class Demo(
    lightbulb.SlashCommand,
    name="demo",
    description="Preview the level-up message as yourself.",
    hooks=[
        prefab_checks.has_permissions(hikari.Permissions.ADMINISTRATOR)
    ],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        member = ctx.member or ctx.user
        msg_json = await bot.settings.get(MESSAGE_KEY)
        if not msg_json:
            await ctx.respond("No level-up message has been set.")
            return
        utils.deep_map(
            msg_json,
            formatter,
            member=utils.member_snapshot(member),
            level_old=1,
            level_new=2,
        )
        await templates.send(ctx, msg_json)


@level.register
class Raw(
    lightbulb.SlashCommand,
    name="raw",
    description="Dump the raw stored level-up message JSON.",
    hooks=[
        prefab_checks.has_permissions(hikari.Permissions.ADMINISTRATOR)
    ],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        msg_json = await bot.settings.get(MESSAGE_KEY)
        await ctx.respond(f"```{json.dumps(msg_json, indent=2)}```")


loader.command(level)
