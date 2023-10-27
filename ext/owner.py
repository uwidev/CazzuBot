"""Debug access for owner."""
import logging
from typing import TYPE_CHECKING

import pendulum
from discord.ext import commands

from src import db, levels_helper, utility


if TYPE_CHECKING:
    from main import CazzuBot


_log = logging.getLogger(__name__)


class Owner(commands.Cog):
    def __init__(self, bot):
        self.bot: CazzuBot = bot

    def cog_check(self, ctx):
        return ctx.author.id == self.bot.owner_id

    async def cog_after_invoke(self, ctx: commands.Context):
        if ctx.command_failed:
            await ctx.message.add_reaction("❌")
        # else:
        #     await ctx.message.add_reaction("✅")

    @commands.command()
    async def owner(self, ctx: commands.Context):
        _log.info("%s is the bot owner.", ctx.author)

    @commands.command()
    async def init_guild(self, ctx: commands.Context):
        await db.guild.add(self.bot.pool, db.GuildSchema(ctx.guild.id))

    @commands.command()
    @utility.author_confirm()
    async def resync_exp(self, ctx: commands.Context):
        _log.info(f"{ctx.author} called for resync of member lifetime exp")
        await db.member.sync_with_exp_logs(self.bot.pool)

    @commands.group()
    async def calc(self, ctx: commands.Context):
        """Helper for calculating all things related to level."""

    @calc.command(name="to")
    async def calc_to(self, ctx: commands.Context, n: int):
        """Calculate the exp required to get from n-1 to n."""
        res = levels_helper.exp_to_level(n)
        await ctx.reply(f"{res:.2f}")

    @calc.command(name="cum")
    async def calc_cum(self, ctx: commands.Context, n: int):
        """Calculate the exp required to get from 0 to n."""
        res = levels_helper.exp_to_level_cum(n)
        await ctx.reply(f"{res:.2f}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Owner(bot))
