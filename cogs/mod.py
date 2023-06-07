"""
This cog contains the implementation of all things related moderation.

TODO Create customized user group and permissions
"""
import logging

import discord
from discord.ext import commands
from discord.ext.commands.context import Context

import db_interface as dbi
import db_settings_aggregator as dsa
from db_settings_aggregator import Table, Scope


_log = logging.getLogger(__name__)


settings = {

}


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def cog_check(self, ctx: Context) -> bool:
        perms = ctx.channel.permissions_for(ctx.author)
        return any([perms.moderate_members,
                    perms.kick_members,
                    perms.ban_members])

    @commands.command()
    async def mod_check(self, ctx: Context):
        await ctx.send("You have moderator permissions!")


async def setup(bot: commands.Bot):
    dsa.register_settings(Table.GUILD_SETTINGS, Scope.DEFAULT, settings)
    await bot.add_cog(Moderation(bot))
