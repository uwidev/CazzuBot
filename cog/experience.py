import discord, db_user_interface
from discord.ext import commands
from utility import timer
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
        
        if message.author.id != self.bot.owner_id:
            return

        if message.author in self._user_cooldown:
            # print('>> {} needs to slow down!'.format(message.author))
            return
        
        self._user_cooldown[message.author] = copy(timer)
        self._user_cooldown[message.author].start(_EXP_COOLDOWN, self.user_cooldowned, message.author)

        db_user_interface.modify_exp(self.bot.db_user, message.author.id, _EXP_BASE)
    
    async def user_cooldowned(self, member):
        self._user_cooldown.pop(member)
        # print(">> Popped {}".format(member.name))


def setup(bot):
    bot.add_cog(Experience(bot))