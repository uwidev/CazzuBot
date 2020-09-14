import discord, db_user_interface
from discord.ext import commands
from utility import Timer, make_simple_embed, PARSE_CLASS_VAR
from copy import copy

import customs.cog

_EXP_BASE = 5
_EXP_COOLDOWN = 5 #seconds

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
        
        # if message.author.id != self.bot.owner_id:
        #     return

        if message.author.id in Experience._user_cooldown_:
            # print('>> {} needs to slow down!'.format(message.author))
            return
        
        Experience._user_cooldown_[message.author.id] = Timer(self.user_cooldowned, seconds=_EXP_COOLDOWN)
        Experience._user_cooldown_[message.author.id].start(message.author)

        db_user_interface.modify_exp(self.bot.db_user, message.author.id, _EXP_BASE)
    

    async def user_cooldowned(self, member):
        '''A callback that removes the member from Experience._user_cooldown so they can receive experience again.'''
        Experience._user_cooldown_.pop(member.id)


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
                if i == placement:
                    compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place='@'+str(i+1), count=int(sorted_users[i]['exp']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                elif i%2:
                    compare += '{place:<8}{count:<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['exp']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                else:
                    compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['exp']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
            compare += '```'

            desc = data + '\n\n' + report + '\n' + compare

            embed = make_simple_embed(title, desc)
            embed.set_thumbnail(url=user.avatar_url)

            await ctx.send(embed=embed)
            
            # await ctx.send('Your current exp is **`{exp}`** with an exp factor of **`x{factor:.2f}`**.'.format(exp=int(exp), factor=factor))


def setup(bot):
    bot.add_cog(Experience(bot))