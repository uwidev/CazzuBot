"""Levels plugin cog — level-up message configuration."""

from discord.ext import commands

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot
from cazzubot.window import window_success

from .logic import MESSAGE_KEY, formatter


class LevelsCog(commands.Cog):
    """Configure the level-up message."""

    def __init__(self, bot: CazzuBot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="level", aliases=["lvl"])
    @commands.has_permissions(administrator=True)
    async def level(self, _ctx: commands.Context[CazzuBot]) -> None:
        pass

    @level.command(name="set", aliases=["msg"])
    async def level_set(
        self, ctx: commands.Context[CazzuBot], *, message: str
    ) -> None:
        """Set the level-up message JSON."""
        decoded = templates.verify(message, formatter, member=ctx.author)
        await self.bot.settings.set(MESSAGE_KEY, decoded)
        await window_success(ctx, "Level-up message set")

    @level.command(name="demo")
    async def level_demo(self, ctx: commands.Context[CazzuBot]) -> None:
        """Preview the level-up message as yourself."""
        msg_json = await self.bot.settings.get(MESSAGE_KEY)
        if not msg_json:
            await ctx.send("No level-up message has been set.")
            return
        utils.deep_map(
            msg_json,
            formatter,
            member=ctx.author,
            level_old=1,
            level_new=2,
        )
        await templates.send(ctx, msg_json)

    @level.command(name="raw")
    async def level_raw(self, ctx: commands.Context[CazzuBot]) -> None:
        """Dump the raw stored level-up message JSON."""
        import json

        msg_json = await self.bot.settings.get(MESSAGE_KEY)
        await ctx.send(f"```{json.dumps(msg_json, indent=2)}```")
