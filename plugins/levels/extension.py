"""Levels plugin extension — level-up message configuration.

Lightbulb extension module: a module-level ``lightbulb.Loader`` holding the
``level`` command group (admin-only).
"""

import json

import hikari
import lightbulb

from cazzubot import templates, utils

from cazzubot.window import window_success

from .logic import MESSAGE_KEY, formatter

loader = lightbulb.Loader()

level = lightbulb.Group(
    "level",
    "Configure the level-up message.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)


@level.register
class Set(
    lightbulb.SlashCommand,
    name="set",
    description="Set the level-up message JSON.",
    hooks=[utils.ADMIN_ONLY],
):
    """Set the level-up message JSON."""

    message = lightbulb.string("message", "The level-up message JSON")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Validate and persist the level-up message JSON."""
        bot = utils.bot_from(ctx)
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
    hooks=[utils.ADMIN_ONLY],
):
    """Preview the level-up message as the invoker."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render the stored message template as a preview."""
        bot = utils.bot_from(ctx)
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
    hooks=[utils.ADMIN_ONLY],
):
    """Dump the raw stored level-up message JSON."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Echo the stored message JSON verbatim."""
        bot = utils.bot_from(ctx)
        msg_json = await bot.settings.get(MESSAGE_KEY)
        await ctx.respond(f"```{json.dumps(msg_json, indent=2)}```")


loader.command(level)
