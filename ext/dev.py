"""Developer commands for sandbox purposes."""
import logging

from discord.ext import commands


# import src.db_interface as dbi
# from src.serializers import TestEnum


_log = logging.getLogger(__name__)


class Dev(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def cog_check(self, ctx):
        return ctx.author.id == self.bot.owner_id

    @commands.command()
    async def owner(self, ctx):
        _log.info("%s is the bot owner.", ctx.author)

    # @commands.command()
    # async def t1(self, ctx):
    #     data = {"foo": TestEnum.FOO}
    #     await dbi.insert_document(self.bot.db, "TEST", data)

    # @commands.command()
    # async def write(self, ctx: commands.Context):
    #     dbi.insert_document(self.bot.db, Table.GUILD_SETTINGS, ctx.guild.id)
    #     dbi.insert_document(self.bot.db, Table.GUILD_MODLOGS, ctx.guild.id)
    #     dbi.insert_document(
    #         self.bot.db,
    #     )

    # @commands.command()
    # async def init(self, ctx: commands.Context):
    #     dbi.initialize(self.bot.db, Table.GUILD_SETTINGS, ctx.guild.id)

    # @commands.command()
    # async def upgrade(self, ctx: commands.Context):
    #     dbi.upgrade(self.bot.db)

    # @commands.command()
    # async def get(self, ctx: commands.Context):
    #     res = dbi.get_by_id(self.bot.db, Table.GUILD_SETTINGS, ctx.guild.id)
    #     _log.warning(res)


async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
