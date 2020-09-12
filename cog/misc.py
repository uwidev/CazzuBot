# This cog houses all commands that can be ran by everyone (a member of a guild).

import discord
from discord.ext import commands

import customs.cog

class MyHelpCommand(commands.MinimalHelpCommand):
        def get_command_signature(self, command):
            return '{0.clean_prefix}{1.qualified_name} {1.signature}'.format(self, command)


class Misc(customs.cog.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._original_help_command = bot.help_command
        bot.help_command = MyHelpCommand()
        bot.help_command.cog = self


    def cog_unload(self):
            self.bot.help_command = self._original_help_command

    
    @commands.command()
    async def hashiresoriyo(self, ctx):
        '''
        Gives you a jolly Saber
        '''
        await ctx.send("https://www.youtube.com/watch?v=rkWk0Nq5GjI")


    @commands.command()
    async def info(self, ctx, *, member: discord.Member):
        '''
        Provides you with basic user information.
        '''
        fmt = '{0} joined on {0.joined_at} and has {1} roles'
        await ctx.send(fmt.format(member, len(member.roles)))


    @commands.command()
    async def noot(self, ctx):
        '''
        Noot noot!
        '''
        await ctx.send("NOOT NOOT")


    @commands.command()
    async def ping(self, ctx):
        await ctx.send(':ping_pong: Pong! {}ms'.format(str(self.bot.latency * 1000)[0:6]))


    @commands.command()
    async def tableflip(self, ctx):
        await ctx.send("(╯°□°）╯︵ ┻━┻")


def setup(bot):
    bot.add_cog(Misc(bot))