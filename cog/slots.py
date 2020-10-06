import asyncio, os
import discord, db_user_interface
from discord.ext import commands
from utility import Timer, make_simple_embed, PARSE_CLASS_VAR
from copy import copy
from random import randint
from time import time

import customs.cog

# This line is added to my linux machine

######################## PAYOUTS ########################
#########################################################
#################    combo     frogs   ##################
#################    7 7 7       25    ##################
#################    6 6 6       15    ##################
#################    5 5 5       15    ##################
#################    5 5 6       13    ##################
#################    4 4 4        7    ##################
#################    4 4 6        6    ##################
#################    3 3 3        5    ##################
#################    3 3 6        4    ##################
#################    2 2 2        3    ##################
#################    2 2 6        2    ##################
#################    1 1 ?        1    ##################
#################    1 ? ?        1    ##################
#########################################################
#########################################################

_SYMBOL_AMOUNT_IN_REEL = 5
_NUM_OF_REELS = 3

# The converter for the slots function
def _is_valid_credits(args):
    return args if args in ('low', 'mid', 'high') else 'stop'

class Slots(customs.cog.Cog):
    # Minimum of 8 emotes required for this to work
    _emotes = [":x:", ":one:", ":two:", ":three:", ":four:", ":five:", ":six:", ":seven:"] # Change/comment out later
    # For future designer(s): change this to change combo->payout
    # The last two payouts will be handled by a helper function
    _combo_payout = {
        _emotes[7]+_emotes[7]+_emotes[7] : 25,
        _emotes[6]+_emotes[6]+_emotes[6] : 15,
        _emotes[5]+_emotes[5]+_emotes[5] : 15,
        _emotes[5]+_emotes[5]+_emotes[6] : 13,
        _emotes[4]+_emotes[4]+_emotes[4] :  7,
        _emotes[4]+_emotes[4]+_emotes[6] :  6,
        _emotes[3]+_emotes[3]+_emotes[3] :  5,
        _emotes[3]+_emotes[3]+_emotes[6] :  4,
        _emotes[2]+_emotes[2]+_emotes[2] :  3,
        _emotes[2]+_emotes[2]+_emotes[6] :  2,
        _emotes[1]+_emotes[1]+_emotes[5] :  1,
        _emotes[1]+_emotes[1]+_emotes[4] :  1,
        _emotes[1]+_emotes[1]+_emotes[3] :  1,
        _emotes[1]+_emotes[1]+_emotes[2] :  1,
        _emotes[1]+_emotes[1]+_emotes[1] :  1,
        _emotes[1]+_emotes[1]+_emotes[0] :  1
        }


    _credits = {
        'low' : 1,
        'mid' : 5,
        'high' : 15
    }


    # credits -> low = 1, mid = 5, high = 15
    @commands.group(alias=['slots'])
    async def slots(self, ctx, credits_index: _is_valid_credits):
        '''
        Runs the slot machine.
        '''

        # if credits_index not in Slots._credits:
        #     await ctx.send("BAKA")
        #     return

        # consumer = ctx.message.author
        # consumer_data = db_user_interface.fetch(self.bot.db_user, consumer.id)
        # consumer_frogs = consumer_data['frogs_normal']

        # if Slots._credits[credits_index] > consumer_frogs:
        #     embed = make_simple_embed('', 'You do not have enough frogs! You only have **`{count}`**'.format(count=consumer_frogs))
        #     await ctx.send(content=consumer.mention, embed=embed)
        #     return

        try:
            db_user_interface.modify_frog(self.bot.db_user, ctx.message.author.id, -Slots._credits[credits_index])
        except KeyError:
            await ctx.send("BAKA!")
            return

        reels = [[] for i in range(0, _NUM_OF_REELS)]
        self._assign_reels(reels)
        message = await ctx.send(content="_")

        await self._roll_reels(reels, message, ctx, credits_index)


    def _assign_reels(self, reels):
        '''This assigns each reel a list of symbols. 
        
        It's designed so that no three straight symbols are the same
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


    async def _roll_reels(self, reels, msg, ctx, credits_index):
        ''' Roll each reel for a certain amount of ticks '''
        bottom_slot0, bottom_slot1, bottom_slot2 = 2, randint(0, _SYMBOL_AMOUNT_IN_REEL - 4), randint(0, _SYMBOL_AMOUNT_IN_REEL - 4)
        reel0_ticks = randint(1, 2)
        reel1_ticks = reel0_ticks + randint(0,1)
        reel2_ticks = reel1_ticks + randint(0,1)
        
        reel0_border = "**:**"
        reel1_border = "**:**"
        reel2_border = "**:**"

        slot_0 = None
        slot_1 = None
        slot_2 = None

        while(reel2_ticks >= 0):
            # LYNDON'S NOTE: making this associated with reel2_ticks
            await asyncio.sleep(0.2)

            command_title = "-CIRNO  SLOTS-"
            divider = "----------------"
            # This is currently designed to accomidate three reels
            # TODO: Make printing strings more modulare for different number of reels
            row0 = "{0}{1}{0} {2}{3}{2} {4}{5}{4}".format(reel0_border, reels[0][(bottom_slot0 - 2) % 5], reel1_border, reels[1][(bottom_slot1 - 2) % 5], reel2_border, reels[2][(bottom_slot2 - 2) % 5])
            row1 = "{0}{1}{0} {2}{3}{2} {4}{5}{4} <".format(reel0_border, reels[0][(bottom_slot0 - 1) % 5], reel1_border, reels[1][(bottom_slot1 - 1) % 5], reel2_border, reels[2][(bottom_slot2 - 1) % 5])
            slot_0 = reels[0][(bottom_slot0 - 1) % 5]
            slot_1 = reels[1][(bottom_slot1 - 1) % 5]
            slot_2 = reels[2][(bottom_slot2 - 1) % 5]
            row2 = "{0}{1}{0} {2}{3}{2} {4}{5}{4}".format(reel0_border, reels[0][bottom_slot0], reel1_border, reels[1][bottom_slot1], reel2_border, reels[2][bottom_slot2])
            content_string = "\n".join([command_title, divider, row0, row1, row2, divider])
            await msg.edit(content = content_string)
            
            reel0_ticks -= 1
            reel1_ticks -= 1
            reel2_ticks -= 1

            if (reel0_ticks > 0):
                bottom_slot0 = (bottom_slot0 + 1) % 5
            else:
                reel0_border = ":"
            if (reel1_ticks > 0):
                bottom_slot1 = (bottom_slot1 + 1) % 5
            else:
                reel1_border = ":"
            if (reel2_ticks > 0):
                bottom_slot2 = (bottom_slot2 + 1) % 5
            else:
                reel2_border = ":"

        payout = Slots._combo_payout.get(slot_0+slot_1+slot_2, 0)
        if (payout > 0):
            win_notif = "|== WIN ==|\n"
            frogos_used = "**{}** used {} frogo(s). You've gained {} frogo(s)! :cirnoYay:".format(ctx.author, Slots._credits[credits_index], payout)
            content_string = "\n".join([content_string, win_notif, frogos_used])
            db_user_interface.modify_frog(self.bot.db_user, ctx.message.author.id, Slots._credits[credits_index] * payout)
        else:
            lost_notif = "|== LOST ==|\n\n"
            frogos_used = "**{}** used {} frogo(s). It's now gone... :(".format(ctx.author, Slots._credits[credits_index])
            content_string = "\n".join([content_string, lost_notif, frogos_used])
        await msg.edit(content = content_string)


def setup(bot):
    bot.add_cog(Slots(bot))
