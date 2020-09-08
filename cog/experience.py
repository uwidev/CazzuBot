import discord, db_user_interface
from discord.ext import commands
from utility import timer, Timer
from copy import copy

_EXP_BASE = 5
_EXP_COOLDOWN = 5 #seconds

class Experience(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._user_cooldown = dict()


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.id == self.bot.user.id:
            return

        if message.author.bot:
            print('>> Saw a bot message and will ignore it...')
            return
        
        # if message.author.id != self.bot.owner_id:
        #     return

        if message.author in self._user_cooldown:
            # print('>> {} needs to slow down!'.format(message.author))
            return
        
        self._user_cooldown[message.author] = Timer(self.user_cooldowned, seconds=_EXP_COOLDOWN)
        await self._user_cooldown[message.author].start(message.author)

        db_user_interface.modify_exp(self.bot.db_user, message.author.id, _EXP_BASE)
    
    async def user_cooldowned(self, member):
        self._user_cooldown.pop(member)


    @commands.group()
    async def exp(self, ctx):
        '''
        Shows everything about you related to your experience points.
        '''
        if ctx.invoked_subcommand is None:
            user_data = db_user_interface.fetch(self.bot.db_user, ctx.message.author.id)
            exp = user_data['exp']
            factor = user_data['exp_factor']
            
            await ctx.send('Your current exp is **`{exp}`** with an exp factor of **`x{factor}`**.'.format(exp=exp, factor=factor))


def setup(bot):
    bot.add_cog(Experience(bot))