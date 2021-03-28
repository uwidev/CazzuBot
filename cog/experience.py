'''
Handles all experience logic.

The amount of experience given to users are based on my Rested Experience (RE) system. This is essentially your daily boost for talking. After _EXP_BUFF_RESET
minutes, the users will be refreshed a buff that will cause their next _EXP_DECAY_UNTIL_BASE messages to yield much more experience than base rates.

To actually gain experience, a user must send a message to chat. A timer with duration _EXP_COOLDOWN will begin. They will be added to a _user_cooldown dict.
Anyone found in this dictionary will be blocked from receiving experience. When the timer finished, it will itself (and thus, the user) from that dict. They
will then be able to receive experience again.
'''
from copy import copy
import asyncio


import discord, db_user_interface, db_guild_interface
from discord.ext import commands, tasks
from utility import Timer, make_simple_embed_t, PARSE_CLASS_VAR, EmbedSummary, is_admin, request_user_confirmation, quick_embed

import customs.cog

# Global Variables for Experience rates
#
# These variables are never meant to be modified except through hard code.
# These variables, especially the cooldown and exp reset, are not changed upon cog reload at the moment.
# Im just having some some problems when it comes to cancelling a task and restarting it. Maybe in the future when I'm more used
# to tasks it might be feasible, but for now, if you ever need to change these values, it's best to restart the bot.
_EXP_BASE = 1
_EXP_BONUS_FACTOR = 20
_EXP_DECAY_UNTIL_BASE = 77
_EXP_DECAY_FACTOR = 2
_EXP_COOLDOWN = 15 #seconds
_EXP_BUFF_RESET = 1440 #mins    |   1440m = 24h

_FUNC_BONUS_EXP = lambda x : max(0, (_EXP_BASE * _EXP_BONUS_FACTOR - _EXP_BASE) - (_EXP_BASE * _EXP_BONUS_FACTOR - _EXP_BASE) * ((x)/_EXP_DECAY_UNTIL_BASE)**_EXP_DECAY_FACTOR)

# Used for to lookup later by levels.py to determine level threshold
RE_MIN_DURATION = _EXP_COOLDOWN * _EXP_DECAY_UNTIL_BASE / 60

# dict of message count to its rewarded exp, starting at 1
RE_MSG_EXP_CUMULATIVE = dict()
RE_MSG_EXP_CUMULATIVE[1] = _EXP_BASE + _FUNC_BONUS_EXP(0)
# print(RE_MSG_EXP_CUMULATIVE[1])
for i in range(2, _EXP_DECAY_UNTIL_BASE+1):
    
    RE_MSG_EXP_CUMULATIVE[i] = RE_MSG_EXP_CUMULATIVE[i-1] + _EXP_BASE + _FUNC_BONUS_EXP(i-1)
    # print(RE_MSG_EXP_CUMULATIVE[i])

_EMBED_SUMMARY_TEMPLATE = '**{name}** **{old}** -> **{new}**'

class Experience(customs.cog.Cog):
    '''
    Experiences uses a _user_cooldown_ dictionary that maps a user.id to a list containing the following
        0 : int : message contributions on this buff interval
        1 : Timer : cooldown until their next message is counted
        2 : Timer : cooldown until their buff is refreshed
    '''
    _user_cooldown_ = dict()

    def __init__(self, bot):
        super().__init__(bot)
        if self._first_load_:
            db_user_interface.reset_exp_factor_all(self.bot.db_user)    


    def cog_unload(self):
        Experience._first_load_ = False
        super().cog_unload()


    @commands.Cog.listener()
    async def on_message(self, message):
        '''Adds experience to the user for the message they sent.

        For a user to be considered eligible to get experience, they must not be a bot and must not have recently
        received experience. Once eligible, {author.id : Timer()} is added to Experience._user_cooldown and their data is
        modified in the database.

        Paramaters
        --------------------
        message : discord.Message
            The message that was send by a certain user.

        Notes
        --------------------
        Soon to be rewritten with extended functionality.
        '''
        if message.author.id == self.bot.user.id:
            return

        if message.author.bot:
            # print('>> Saw a bot message and will ignore it...')
            return

        if message.author.id not in Experience._user_cooldown_:     # then track the user and start timers
            Experience._user_cooldown_[message.author.id] = [0, Timer(lambda *args: None, seconds=_EXP_COOLDOWN), Timer(self.user_reset_count, minutes=_EXP_BUFF_RESET)]
            Experience._user_cooldown_[message.author.id][1].start(message.author)
            Experience._user_cooldown_[message.author.id][2].start(message.author)
            # the value for Experience._user_cooldown_ is [count, Timer exp cooldown, Timer exp buff]     
        elif Experience._user_cooldown_[message.author.id][1].is_running:   # if exp on cd, return and don't do anything
            return

        # if program gets to this point, it means that either the user's message cooldown has expired (can receive exp), or this is their first message since
        # their buff refresh, or the bot went offline and data on message counts per user was lost.
        guild_settings_exp = db_guild_interface.fetch(self.bot.db_guild, message.guild.id)['experience']

        # because we are taking into account the guild's experience factor, experience is essentially guild-specific at this point.
        # this means that all user.db contains data specifically for this guild
        #
        # in other words, user data WILL BLEED TO OTHER GUILDS IF YOU DO NOT DIFFERENTIATE THE TWO
        if str(message.channel.id) in guild_settings_exp['channel_factors']:
            msg_value = guild_settings_exp['channel_factors'][str(message.channel.id)]
        else:
            msg_value = 1

        # if the old message contributions is a new whole number above the new, grant the user the new experience
        # otherwise DO NOTHING
        contribution_old = Experience._user_cooldown_[message.author.id][0]
        contribution_new = contribution_old + msg_value
        
        diff = int(contribution_new) - int(contribution_old)
        Experience._user_cooldown_[message.author.id][0] = contribution_new
        Experience._user_cooldown_[message.author.id][1].restart()
        
        db_member = db_user_interface.fetch(self.bot.db_user, message.author.id)
        old_exp = db_member['exp']
        
        if diff != 0:
            embed = EmbedSummary()
            member_exp = old_exp
            count = contribution_old
            
            for _ in range(diff):
                bonus_exp = _FUNC_BONUS_EXP(count)
                total_bonus_exp = _EXP_BASE + bonus_exp
                member_exp += total_bonus_exp
                count += 1

            embed = await self.bot.get_cog("Levels").on_experience(message, old_exp, member_exp)
            if embed.touched:
                discord_embed = make_simple_embed_t(embed.title, embed.description.format(user=message.author.mention))
                discord_embed.set_thumbnail(url=embed.thumbnail)
                discord_embed.color = embed.color
                discord_embed.add_field(name = '__**Summary**__', 
                    value = '\n'.join(_EMBED_SUMMARY_TEMPLATE.format(name=key, old=val[0], new=val[1]) for key,val in embed.payload.items()),
                    inline = False)
                
                await message.channel.send(message.author.mention, embed=discord_embed)
            
            print(f'>> [EXP] {message.author}\t::\t{int(old_exp)} => {int(member_exp)}\t::\t{member_exp-old_exp:.2f}\t::\t{Experience._user_cooldown_[message.author.id][0]}')
            
            db_user_interface.set_user_exp(self.bot.db_user, message.author.id, member_exp)


    async def user_reset_count(self, member):
        '''A callback that removes the user from being tracked in _user_cooldown_ once enough time has passed.'''
        del Experience._user_cooldown_[member.id]


    @commands.group(aliases=['xp'], invoke_without_command=True)
    async def exp(self, ctx, *, user:discord.Member = None):
        '''Shows everything about you related to your experience points.

        Provide a user to see their stats instead.
        '''
        if user == None:
            user = ctx.message.author

        user_data = db_user_interface.fetch(self.bot.db_user, user.id)
        
        sorted_users = db_user_interface.fetch_all(self.bot.db_user)
        sorted_users.sort(key=lambda user: user['exp'], reverse=True)

        sorted_users_ids = list(map(lambda user: user['id'], sorted_users))
        placement = sorted_users_ids.index(user.id)

        title = '{user}\'s Club Membership Card'.format(user=user.display_name)
        
        rank_id = user_data['rank']
        rank = ctx.guild.get_role(rank_id)
        level = user_data['level']
        exp = user_data['exp']
        # factor = user_data['exp_factor']

        # data = 'Rank: {rk}\nExperience: **`{xp}`**\nExperience Factor: **`x{fa:.2f}`**'.format(rk=rank.mention, xp=int(exp), fa=factor)
        data = 'Rank: {rk}\nLevel: **`{lvl}`**\nExperience: **`{xp}`**'.format(rk=rank.mention, lvl=level, xp=int(exp))
        report = '{user} are ranked **`#{place}`** out of **`{total}`**!'.format(user='You' if ctx.message.author == user else user.mention, place=placement + 1, total=len(sorted_users))
        
        compare = '```py\n{place:8}{mode:<8}{user:20}\n'.format(place='Place', mode='Exp', user='User')
        for i in range(max(0, placement-2), min(placement+3, len(sorted_users))):
            try:
                if i == placement:
                    compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place='@'+str(i+1), count=int(sorted_users[i]['exp']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                elif i%2:
                    compare += '{place:<8}{count:<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['exp']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                else:
                    compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['exp']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
            except AttributeError:
                if i == placement:
                    compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place='@'+str(i+1), count=int(sorted_users[i]['exp']), user=(await self.bot.fetch_user(sorted_users[i]['id'])).display_name)
                elif i%2:
                    compare += '{place:<8}{count:<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['exp']), user=(await self.bot.fetch_user(sorted_users[i]['id'])).display_name)
                else:
                    compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['exp']), user=(await self.bot.fetch_user(sorted_users[i]['id'])).display_name)
        compare += '```'

        desc = data + '\n\n' + report + '\n' + compare

        embed = make_simple_embed_t(title, desc)
        embed.set_thumbnail(url=user.avatar_url)

        await ctx.send(embed=embed)
        
        # await ctx.send('Your current exp is **`{exp}`** with an exp factor of **`x{factor:.2f}`**.'.format(exp=int(exp), factor=factor))


    @exp.group(name='rate', aliases=['rates'], invoke_without_command=True)
    @is_admin()
    async def exp_rate(self, ctx, rate:float=None, *, channel:discord.TextChannel=None):
        '''
        Adjusts the experience rate of a channel for a guild.
        '''
        # Currently if rate = 1 it will still write it. This is redundant because when checking the doc for
        # the channel exp factor, if not found it default to one
        #
        # You  would have to mess with formatting to 
        settings = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        settings_exp = settings['experience']
        
        if rate == None and channel == None:
            template = '{channel} => **`x{rate}`**'
            summary = '\n'.join(template.format(channel=ctx.guild.get_channel(int(k)).mention, rate=v) for k, v in settings_exp['channel_factors'].items())
            if summary is None:
                summary = 'The server is using default rates!'
            embed = make_simple_embed_t(f'{ctx.guild.name}\'s Experience Rates per Channel', summary)
            embed.set_thumbnail(url=ctx.guild.icon_url)

            await ctx.send(embed=embed)
            
            return
        
        if channel == None:
            channel = ctx.channel

        settings_exp['channel_factors'][str(channel.id)] = rate
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, settings)
        await quick_embed(ctx, 'success', f'{ctx.channel.mention} now has an experience rate of {rate}.')


    @exp_rate.command(name='clear', invoke_without_command=True)
    @is_admin()
    async def exp_rate_clear(self, ctx):
        if await request_user_confirmation(ctx, self.bot, 'Are you sure you would like to clear experience rates for the server?', delete_after=True):
            settings = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
            settings_exp = settings['experience']['channel_factors'].clear()
            db_guild_interface.write(self.bot.db_guild, ctx.guild.id, settings)

            await quick_embed(ctx, 'success', f'Server experience rates have been cleared!')
        
    
    @exp.command(name='reset')
    @is_admin()
    async def exp_reset(self, ctx):
        if await request_user_confirmation(ctx, self.bot, 'Are you sure you would like reset all member\'s experience?', delete_after=True):
            if await request_user_confirmation(ctx, self.bot, 'You sure?', delete_after=True):
                wait_for_me = await ctx.send('Doing the deed...')
                async with ctx.typing():
                    db_user_interface.reset_exp_all(self.bot.db_user)

                await wait_for_me.delete()
        
        await quick_embed(ctx, 'success', f'Server experience for all members have been reset!')



    @commands.group(name='logexp', aliases=['logxp'], invoke_without_command=True)
    @commands.is_owner()
    async def log_exp(self, ctx):
        if ctx.invoked_subcommand is None:
            if self.exp_logger.is_running():
                await ctx.send('I am currently logging experience.')
            else:
                await ctx.send('I am currently **not** logging experience.')
    

    @log_exp.command(name='start')
    @commands.is_owner()
    async def log_exp_start(self, ctx):
        try:
            self.exp_logger.start()
        except RuntimeError:
            await ctx.send('Already logging experience!')
            return

        await ctx.send('Will now start logging experience over time...')

    
    @log_exp.command(name='stop')
    @commands.is_owner()
    async def log_exp_stop(self, ctx):
        if self.exp_logger.is_running():
            self.exp_logger.stop()
            await ctx.send('Will stop logging experience...')
        else:
            await ctx.send('Was never logging to begin with...')


    @tasks.loop(minutes=60)
    async def exp_logger(self):
        with open('exp_log.csv', 'a') as log:
            all_users = db_user_interface.fetch_all(self.bot.db_user)

            log.write(','.join(str(user['exp']) for user in all_users) + '\n')


def setup(bot):
    bot.add_cog(Experience(bot))
