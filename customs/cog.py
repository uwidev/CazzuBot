'''
This cog allows for hotswapping of cogs while retaining data that was kept as specially marked class variables.
Class variables that are meant to be kept when hotswapping are denoed with a leading and trailing single underscore.

Example
====================
class A(commands.Cog):
    var_A
    _var_B_

    def self.__init__(self):
        self.var_a
        self._var_b_
====================

The only variable that will be carried over will be "A._var_B_", the rest discarded in favor of changes from some
external update. Note that data that carries over should only be considered volatile; data that is created at runtime
and is required for extended operations e.g. cooldown timers.
'''

import discord
from discord.ext import commands

from utility import PARSE_CLASS_VAR

class Cog(commands.Cog):
    def __init__(self, bot):
        '''super() should be called from the child to enable hotswapping.'''
        self.bot = bot

        data = self.bot.data_to_return.get(type(self).__name__, None)
        if data:
            for key, val in data.items():
                print(f'settings {key} : {val} onto {type(self)}')
                setattr(type(self), key, val)
        
            del self.bot.data_to_return[type(self).__name__]

    def cog_unload(self):
        data = vars(type(self))
        data = dict(filter(lambda pair: PARSE_CLASS_VAR.match(pair[0]), data.items()))
        
        self.bot.data_to_return[type(self).__name__] = data