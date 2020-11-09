import discord, db_user_interface
from discord.ext import commands, tasks
from utility import Timer, make_simple_embed, PARSE_CLASS_VAR
from copy import copy

import customs.cog

_EXP_BASE = 5
_EXP_BONUS_FACTOR = 5
_EXP_DECAY_UNTIL_BASE = 30
_EXP_DECAY_FACTOR = 3
_EXP_COOLDOWN = 6 #seconds
_EXP_BUFF_RESET = 15 #mins

class Experience(customs.cog.Cog):
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
        elif Experience._user_cooldown_[message.author.id][1].is_running:   # if exp on cd
            return

        Experience._user_cooldown_[message.author.id][0] += 1
        Experience._user_cooldown_[message.author.id][1].restart()

        potential_bonus = (_EXP_BASE * _EXP_BONUS_FACTOR - _EXP_BASE)
        count = Experience._user_cooldown_[message.author.id][0]
        bonus_exp = max(0, potential_bonus - potential_bonus * ((count-1)/_EXP_DECAY_UNTIL_BASE)**_EXP_DECAY_FACTOR)
        total_exp = _EXP_BASE + bonus_exp

        db_user_interface.modify_exp(self.bot.db_user, message.author.id, total_exp)


    async def user_reset_count(self, member):
        '''A callback that removes the user from being tracked in _user_cooldown_ once enough time has passed.'''
        del Experience._user_cooldown_[member.id]


    @commands.group(aliases=['xp'])
    async def exp(self, ctx, *, user:discord.Member=None):
        '''Shows everything about you related to your experience points.

        Provide a user to see their stats instead.
        '''
        if ctx.invoked_subcommand is None:
            if user == None:
                user = ctx.message.author

            user_data = db_user_interface.fetch(self.bot.db_user, user.id)
            
            sorted_users = db_user_interface.fetch_all(self.bot.db_user)
            sorted_users.sort(key=lambda user: user['exp'], reverse=True)

            sorted_users_ids = list(map(lambda user: user['id'], sorted_users))
            placement = sorted_users_ids.index(user.id)

            title = '{user}\'s Experience Report Card'.format(user=user.display_name)
            
            exp = user_data['exp']
            factor = user_data['exp_factor']

            data = 'Experience: **`{xp}`**\nExperience Factor: **`x{fa:.2f}`**'.format(xp=int(exp), fa=factor)
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

            embed = make_simple_embed(title, desc)
            embed.set_thumbnail(url=user.avatar_url)

            await ctx.send(embed=embed)
            
            # await ctx.send('Your current exp is **`{exp}`** with an exp factor of **`x{factor:.2f}`**.'.format(exp=int(exp), factor=factor))


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


    @tasks.loop(minutes=15)
    async def exp_logger(self):
        with open('exp_log.csv', 'a') as log:
            all_users = db_user_interface.fetch_all(self.bot.db_user)

            log.write(','.join(str(user['exp']) for user in all_users) + '\n')


def setup(bot):
    bot.add_cog(Experience(bot))
