'''
Contains the logic for levels based on experience. Experience needed for level are oscillating, based on what I'm calling Consecutive Easing Levels (CEL) which 
is the concept of dropping the threshold to level up at regular intervals of levels.

Initial functions are based on how many minutes of real discussion a user has participated in. This will eventually need to be converted into experience.
'''

from math import sin, pi, floor, inf, ceil

import discord
from discord.ext import commands

import db_user_interface
import customs.cog
from utility import make_simple_embed_t, EmbedSummary
from cog.experience import \
    _EXP_BASE, _EXP_BONUS_FACTOR, _EXP_BUFF_RESET, \
    _EXP_COOLDOWN, _EXP_DECAY_FACTOR, _EXP_DECAY_FACTOR, \
    _EXP_DECAY_UNTIL_BASE, _FUNC_BONUS_EXP, RE_MIN_DURATION, \
    RE_MSG_EXP_CUMULATIVE

# from cog.ranks import \
#     _RANK_EMBED_TITLE, _RANK_EMBED_DESCRIPTION, _RANK_EMBED_THUMBNAIL, \
#     _RANK_EMBED_COLOR

# ==============================================================
# Level Change Embed
# ==============================================================
_LEVEL_EMBED_TITLE = 'Level Up! 🎉'
_LEVEL_EMBED_DESCRIPTION = 'Congratulations {user}, you have reached a new level!'
_LEVEL_EMBED_THUMBNAIL = 'https://i.imgur.com/kCHjymJ.png'
_LEVEL_EMBED_COLOR = 0x9EDDF5

_EMBED_SUMMARY_TEMPLATE = '**{name}** **{old}** -> **{new}**'


# ==============================================================
# Formula Variables for level-threshold calculations
# ==============================================================
# "Class" variables are in global scope because of lambda's troublesome scoping. It can't access class variables!!!
# Upper Bound on Level Thresholds
_LEVELS_UPPER_BOUND_LOWER_LIMIT = 3.0
_LEVELS_UPPER_BOUND_UPPER_LIMIT = 15.0
_LEVELS_UPPER_BOUND_CURVE = 55.0

# Lower Bound for on CE
_LEVELS_LOWER_BOUND_LOWER_LIMIT = -1
_LEVELS_LOWER_BOUND_UPPER_LIMIT = -6.401
_LEVELS_LOWER_BOUND_CURVE = 35.0

# Sin function for CE
_LEVELS_CE_POWER = 10.0
_LEVELS_CE_OFFSET = 0.0
_LEVELS_CE_INTERVAL = 10.0

class Levels(customs.cog.Cog):
# class Levels(commands.Cog):
    # ==============================================================
    # Class Variables and low-level formulas setup
    # ==============================================================
    '''
    This formula maps real minutes talking to experience thresholds.
    '''
    def _FUNC_UPPER_BOUND(self, x):
        return _LEVELS_UPPER_BOUND_LOWER_LIMIT + \
                    ((float(x) * (_LEVELS_UPPER_BOUND_UPPER_LIMIT-_LEVELS_UPPER_BOUND_LOWER_LIMIT)) 
                    / 
                    (float(x) + _LEVELS_UPPER_BOUND_CURVE))
    
    def _FUNC_LOWER_BOUND(self, x): 
        return _LEVELS_LOWER_BOUND_LOWER_LIMIT + ((float(x)*(_LEVELS_LOWER_BOUND_UPPER_LIMIT-_LEVELS_LOWER_BOUND_LOWER_LIMIT)) / (float(x) + _LEVELS_LOWER_BOUND_CURVE))
    
    def _CE(self, x):
        return -abs( (_LEVELS_CE_POWER*sin( (float(x)+_LEVELS_CE_OFFSET+_LEVELS_CE_INTERVAL)/_LEVELS_CE_INTERVAL*pi ) * self._FUNC_LOWER_BOUND(float(x))) 
                      /
                     (_LEVELS_CE_OFFSET + _LEVELS_CE_INTERVAL) )


    # Combining to form final equation, adjusted +1 so level 1 starts at x=0
    def _FUNC_LEVEL_MINUTE_THRESHOLDS(self, x):
        return self._FUNC_UPPER_BOUND(x) + self._CE(x)
    
    _LEVEL_MINUTE_THRESHOLDS = dict()
    _LEVEL_MINUTE_THRESHOLDS_CUMULATIVE = dict()
        
    '''
    Determining experience threshold based on required minutes spent talking.

    We assume a user only talks during when their experience buff is active. The duration of this buff is based on the RE system under experience.py.

    LEVEL_THRESHOLDS is a dict of total experience requirement to get to level X.
    '''
    LEVEL_THRESHOLDS = dict()
    LEVEL_THRESHOLDS_INV = dict()
    

    # ==============================================================
    # END CLASS MEMBER VARIABLES
    # ==============================================================


    def __init__(self, bot):
        super().__init__(bot)

        # Precompute all levels 1-999 and store them for later use so we don't recompute.
        # For future proofing consider adding appending further calculations.
        Levels._LEVEL_MINUTE_THRESHOLDS[0] = 0
        Levels._LEVEL_MINUTE_THRESHOLDS[1] = 3 # Level 1 will always require 3 minutes of talking
        
        for i in range(2, 1000):
            Levels._LEVEL_MINUTE_THRESHOLDS[i] = self._FUNC_LEVEL_MINUTE_THRESHOLDS(i)
        
        # for i in range(0, 101):
        #     print(f'{i:2d}     :     {self._LEVEL_MINUTE_THRESHOLDS[i]}')

        # print('sum is', sum(Levels._LEVEL_MINUTE_THRESHOLDS.values()))

        # Cumulative thresholds in minutes
        Levels._LEVEL_MINUTE_THRESHOLDS_CUMULATIVE[0] = Levels._LEVEL_MINUTE_THRESHOLDS[0]
        Levels._LEVEL_MINUTE_THRESHOLDS_CUMULATIVE[1] = Levels._LEVEL_MINUTE_THRESHOLDS[1]
        for i in range(2, 1000):
            Levels._LEVEL_MINUTE_THRESHOLDS_CUMULATIVE[i] = Levels._LEVEL_MINUTE_THRESHOLDS_CUMULATIVE[i-1] + Levels._LEVEL_MINUTE_THRESHOLDS[i]

        # for i in range(0, 101):
        #     print(f'{i:2d}     :     {Levels._LEVEL_MINUTE_THRESHOLDS_CUMULATIVE[i]}')

        # Calculation and creation of LEVEL_THRESHOLDS, which is a mapping of level -> total_exp
        Levels.LEVEL_THRESHOLDS[0] = 0
        for i in range(1, 1000):
            # Divide the total messages sent by the limit messages per buff interval
            wake_days = Levels._LEVEL_MINUTE_THRESHOLDS_CUMULATIVE[i]*60 / _EXP_COOLDOWN / _EXP_DECAY_UNTIL_BASE
            
            # Determine the left over minutes
            minutes_leftover = Levels._LEVEL_MINUTE_THRESHOLDS_CUMULATIVE[i] - floor(wake_days) * RE_MIN_DURATION
            
            # Convert the full minute intervals into experience
            threshold_interval = RE_MSG_EXP_CUMULATIVE[_EXP_DECAY_UNTIL_BASE] * floor(wake_days)

            # Convert left over minutes into experience
            messages_leftover = ceil(minutes_leftover*60 / _EXP_COOLDOWN)
            threshold_left_over = RE_MSG_EXP_CUMULATIVE[messages_leftover]

            # Finally, add to our list
            Levels.LEVEL_THRESHOLDS[i] = threshold_interval + threshold_left_over
        

        # for i in range(0, 101):
        #     print(f'{i:2d}     :     {Levels.LEVEL_THRESHOLDS[i]}')

        # Reverse mapping for determining where a user is on levels
        Levels.LEVEL_THRESHOLDS_INV = {v:k for k, v in Levels.LEVEL_THRESHOLDS.items()}

        # Debug
        # for i in [0, 1, 2, 3]:
        #     print(Levels.LEVEL_THRESHOLDS[i])


    async def from_experience(self, exp:float):
        # Equation below will find the nearest fit level and round down.
        return min(Levels.LEVEL_THRESHOLDS.items(), key=lambda kv: (1 if exp >= kv[1] else float('inf')) * abs(kv[1]-exp))[0]

    @commands.command()
    async def exp_level(self, ctx, exp:float):
        # Equation below will find the nearest fit level and round down.
        await ctx.send(f'You will be level {await self.from_experience(exp)}.')

    @commands.command()
    async def level_exp(self, ctx, exp: float):
        if exp < 1 or exp > 999:
            return
       
        # await ctx.send(f'You need {int(self.LEVEL_THRESHOLDS[exp])} experience.')
        # print(f'You need {int(self.LEVEL_THRESHOLDS[exp])} experience.')

        return self.LEVEL_THRESHOLDS[exp]


    @commands.command()
    async def level_minutes(self, ctx, exp: float):
        if exp < 1 or exp > 999:
            return
       
        await ctx.send(f'You need {int(self._LEVEL_MINUTE_THRESHOLDS_CUMULATIVE[exp])} minutes.')


    async def summary_payload(self, level_old, level_new):
        assert(level_old != level_new)

        payload = dict()
        payload['Level'] = (level_old, level_new)

        return payload


    async def on_experience(self, message: discord.Message, exp_old: int, exp_new: int):
        channel = message.channel
        member = message.author
        exp_new = int(exp_new)
        cog_ranks = self.bot.get_cog('Ranks')
        db_member = db_user_interface.fetch(self.bot.db_user, member.id)
        embed = EmbedSummary()
        
        
        level_old = db_member['level']
        level_new = await self.from_experience(exp_new)
        
        # Handle level changes
        if level_old != level_new:
            db_member['level'] = level_new
            db_user_interface.write(self.bot.db_user, member.id, db_member)

            print('\n//////////////////////////////////////////////////////////////')
            print(f"/// {member} has changed levels from {level_old} to {level_new}!")
            print('//////////////////////////////////////////////////////////////\n')
            
        # Summary
        if level_old < level_new:
            embed = EmbedSummary(_LEVEL_EMBED_TITLE, _LEVEL_EMBED_DESCRIPTION, _LEVEL_EMBED_THUMBNAIL, _LEVEL_EMBED_COLOR, await self.summary_payload(level_old, level_new))
        

        # Further calls that depend on levels
        embed_ranks = await cog_ranks.on_experience(message, level_new)
        
        embed.merge_left(embed_ranks)
        return embed
            


    async def summary_order(self, summary, order:list):
        ordered_summary = dict()
        for stat in order:
            if stat in summary:
                ordered_summary[stat] = summary[stat]
        
        return ordered_summary


    async def on_level_up(self, channel, member, title, desc, thumbnail, summary_dict:dict):
        embed = make_simple_embed_t(title, desc.format(user=member.name))
        
        summary = '\n'.join(_EMBED_SUMMARY_TEMPLATE.format(name=key, old=val[0], new=val[1]) for key,val in summary_dict.items())
        
        embed.add_field(name='__Summary__', value=summary, inline=False)
        embed.set_thumbnail(url=thumbnail)

        # print(f'title: {embed.title}\ndesc: {embed.description}\nsummary: {summary}')
        await channel.send(member.mention, embed=embed)




def setup(bot):
    bot.add_cog(Levels(bot))
