import discord, db_user_interface
from discord.ext import commands
from utility import Timer, make_simple_embed, PARSE_CLASS_VAR
from copy import copy
from random import randint

import customs.cog

_SYMBOL_AMOUNT_IN_REEL = 5
_NUM_OF_REELS = 3

class Slots(customs.cog.Cog):
    _emotes = [":one:", ":two:", ":three:", ":four:", ":five:", ":six:", ":seven:", ":x:"]
    _reels = [[] for i in range(0, _NUM_OF_REELS)]

    def __init__(self, bot):
        super().__init__(bot)
        if self._first_load_:
            pass
            # db_user_interface.reset_exp_factor_all(self.bot.db_user)


    def cog_unload(self):
        super().cog_unload()


    @commands.group(alias=['slots'])
    async def slots(self, ctx, *, user:discord.Member=None):
        ran_index_1, ran_index_2, ran_index_3 = randint(0, len(Slots._emotes)-1), randint(0, len(Slots._emotes)-1), randint(0, len(Slots._emotes)-1)
        self._assign_reels()
        await ctx.send("{slot_0} : {slot_1} : {slot_2}\n{slot_3} : {slot_4} : {slot_5}\n{slot_6} : {slot_7} : {slot_8}"\
            .format(slot_0=Slots._reels[0][0], slot_1=Slots._reels[1][0], slot_2=Slots._reels[2][0], \
            slot_3=Slots._reels[0][1], slot_4=Slots._reels[1][1], slot_5=Slots._reels[2][1], \
            slot_6=Slots._reels[0][2], slot_7=Slots._reels[1][2], slot_8=Slots._reels[2][2]))
        # .format(slot_1=Slots._reels[0][0], slot_2=Slots._reels[1][0], slot_3=Slots._reels[2][0]))
        # await ctx.send("{slot_1} : {slot_2} : {slot_3}".format(slot_1=Slots._reels[0][1], slot_2=Slots._reels[1][1], slot_3=Slots._reels[2][1]))
        # await ctx.send("{slot_1} : {slot_2} : {slot_3}".format(slot_1=Slots._reels[0][2], slot_2=Slots._reels[1][2], slot_3=Slots._reels[2][2]))
        # await ctx.send("{slot_1} {slot_2} {slot_3}".format(slot_1=Slots._emotes[ran_index_1], slot_2=Slots._emotes[ran_index_2], slot_3=Slots._emotes[ran_index_3]))


    def _reset_reels(self):
        for reel in Slots._reels:
            reel.clear()


    def _assign_reels(self):
        self._reset_reels()

        for reel in Slots._reels:
            prev_index_1 = None
            prev_index_2 = None
            for i in range(0, _SYMBOL_AMOUNT_IN_REEL):
                current_index = randint(0, len(Slots._emotes)-1)
                while(current_index == prev_index_1 or current_index == prev_index_2):
                    print((prev_index_1, prev_index_2, current_index))
                    current_index = randint(0, len(Slots._emotes)-1)
                prev_index_2 = prev_index_1
                prev_index_1 = current_index
                reel.append(Slots._emotes[current_index])
            

def setup(bot):
    bot.add_cog(Slots(bot))
