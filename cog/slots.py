import asyncio, os
import discord, db_user_interface
from discord.ext import commands
from utility import Timer, make_simple_embed, PARSE_CLASS_VAR
from copy import copy
from random import randint
from time import time

import customs.cog

_SYMBOL_AMOUNT_IN_REEL = 5
_NUM_OF_REELS = 3

class Slots(customs.cog.Cog):
    _emotes = [":one:", ":two:", ":three:", ":four:", ":five:", ":six:", ":seven:", ":x:"] # Change later
    _update_speed_secs = 1 # there can be two events every second

    @commands.group(alias=['slots'])
    async def slots(self, ctx, *, user:discord.Member=None):
        '''
        Runs the slot machine.
        '''

        reels = [[] for i in range(0, _NUM_OF_REELS)]
        self._assign_reels(reels)
        # The line at the bottom is disgusting. Change it when you get the chance.
        message = await ctx.send("{slot_0} : {slot_1} : {slot_2}\n{slot_3} : {slot_4} : {slot_5}\n{slot_6} : {slot_7} : {slot_8}"\
            .format(slot_0=reels[0][0], slot_1=reels[1][0], slot_2=reels[2][0], \
            slot_3=reels[0][1], slot_4=reels[1][1], slot_5=reels[2][1], \
            slot_6=reels[0][2], slot_7=reels[1][2], slot_8=reels[2][2]))

        await self._roll_reels(reels, message)
        # await message.edit(content = "{slot_0} : {slot_1} : {slot_2}\n{slot_3} : {slot_4} : {slot_5}\n{slot_6} : {slot_7} : {slot_8}"\
        #     .format(slot_0=reels[0][1], slot_1=reels[1][0], slot_2=reels[2][0], \
        #     slot_3=reels[0][2], slot_4=reels[1][1], slot_5=reels[2][1], \
        #     slot_6=reels[0][3], slot_7=reels[1][2], slot_8=reels[2][2]))


    def _assign_reels(self, reels):
        '''This assigns each reel a list of symbols. 
        
        It's designed so that no three stright symbols are the same
        '''

        for reel in reels:
            prev_index_1 = None
            prev_index_2 = None
            for i in range(0, _SYMBOL_AMOUNT_IN_REEL):
                current_index = randint(0, len(Slots._emotes)-1)
                while(current_index == prev_index_1 or current_index == prev_index_2):
                    current_index = randint(0, len(Slots._emotes)-1)
                prev_index_2 = prev_index_1
                prev_index_1 = current_index
                reel.append(Slots._emotes[current_index])


    async def _roll_reels(self, reels, msg):
        ''' Roll each reel for a certain amount of ticks '''
        bottom_slot0, bottom_slot1, bottom_slot2 = 2, randint(0, 4), randint(0, 4)
        reel0_ticks, reel1_ticks, reel2_ticks = randint(5, 10), reel0_ticks + randint(1, 3), reel1_ticks(1, 3)
        elapsed = 0
        start = round(time(), 3)
        stop = start + Slots._update_speed_secs
        
        while(elapsed < Slots._update_speed_secs):
            content_string = ""
            await msg.edit(content = "{slot_0} : {slot_1} : {slot_2}\n{slot_3} : {slot_4} : {slot_5}\n{slot_6} : {slot_7} : {slot_8}"\
                .format(slot_0=reels[0][(bottom_slot0 - 2) % 5], slot_1=reels[1][0], slot_2=reels[2][0], \
                slot_3=reels[0][(bottom_slot0 - 1) % 5], slot_4=reels[1][1], slot_5=reels[2][1], \
                slot_6=reels[0][bottom_slot0], slot_7=reels[1][2], slot_8=reels[2][2]))
            # elapsed = round(time(), 3) - start
            elapsed += 0.02
            bottom_slot0 = (bottom_slot0 + 1) % 5
            bottom_slot1 = (bottom_slot1 + 1) % 5
            bottom_slot2 = (bottom_slot2 + 1) % 5

            print(elapsed)

            temp = elapsed
            # if (elapsed >= 0.35):
            #     temp = 0.35
            # print(temp)
            await asyncio.sleep(1)
        print("stop")

def setup(bot):
    bot.add_cog(Slots(bot))
