import sys

import discord
from discord.ext import commands, tasks
import db_user_interface, db_guild_interface
import asyncio
from utility import make_simple_embed, timer, Timer
from random import uniform
from copy import copy

# Later, read these vars from some db on startup
_SPAWNRATE_DEFAULT = 5 #minutes
_SPAWNRATE_SWING = .35 #within 20% offsets
_TIMEOUT = 10

# -----------
#
# The elements used on frog spawn
# Initial Spawning
_SPAWN = '<:cirnoFrog:752291209535291453>'
_REACT = '<:cirnoNet:752290769712316506>'

# Successful catch
_CONGRATS = 'Congrats on your catch!'
_DELTA = '+1 to froggies'
_RESULT = '**Total froggies: `{old}` -> `{new}`**'
_URL_CAUGHT = 'https://i.imgur.com/uwPIHMv.png'

# Failure
_FAIL = 'You were too slow!'

# ----------
#
# Consumption of frogs
_EXP_FACTOR_PER_FROG = .1
_EXP_FACTOR_CAP = 1.5


class Frogs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._frogs_spawner = list()

    
    async def cog_command_error(self, ctx, error):

        # This statement checks to see if the command has a local error handler,
        # and if so, don't run the cog error handler
        if hasattr(ctx.command, 'on_error'):
            return

        if isinstance(error, commands.MissingPermissions):
            await ctx.send('You are missing the following permissions: `{}`'.format(', '.join(error.missing_perms)))
        else:
            print('Ignoring exception from command {}:'.format(ctx.command), file=sys.stderr)
            raise(error)


    class Spawner():
        def __init__(self, channel: discord.TextChannel, base_rate: int, timer):
            self._channel = channel
            self._base_rate = base_rate
            self._timer = timer
            self._first_spawn = True
            self._first_spawn_task = None

        async def start(self, seconds=0, minutes=0):
            if self._first_spawn:
                await asyncio.sleep(seconds + 60 * minutes)
                self._first_spawn = False
            self.change_interval_random()
            self._timer.start(self)

        def stop(self):
            self._first_spawn_task.cancel()
            self._timer.cancel()

        def change_interval(self, **kwargs):
            self._timer.change_interval(**kwargs)

        def change_interval_random(self):
            self._timer.change_interval(minutes=self.random_spawn_time())

        def random_spawn_time(self):
            new = _SPAWNRATE_SWING*self._base_rate*uniform(-1, 1) + self._base_rate
            # print('>> changing to {:.2f} minutes ({:2f} seconds)'.format(new, new*60))
            return new

        def get_channel(self):
            return self._channel

        def set_first_spawn_task(self, task):
            self._first_spawn_task = task

        def get_first_spawn_task(self):
            return self._first_spawn_task


    @commands.group(aliases=['frog'])
    async def frogs(self, ctx):
        '''
        Shows everything about you related to frogs.
        '''
        if ctx.invoked_subcommand is None:
            user_data = db_user_interface.fetch(self.bot.db_user, ctx.message.author.id)
            frogs = user_data['frogs']
            
            await ctx.send('You currently have **`{count}`** frog(s).'.format(count = frogs))


    @frogs.command()
    @commands.is_owner()
    async def fspawn(self, ctx):
        # Force a frog to spawn
        await self.spawn(ctx.channel)


    @frogs.command()   
    @commands.has_guild_permissions(manage_guild=True) 
    async def start(self, ctx):
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        frogs_settings = guild_conf['frogs']

        if len(frogs_settings['channel_rates']) <= 0:
            await ctx.send('You have not registerd any channels to spawn frogs!')
            return

        if frogs_settings['op']:
            await ctx.send('Frogs are already spawning!')
            return
    
        frogs_settings['op'] = True

        channel_rates = list((ctx.guild.get_channel(cr[0]), cr[1]) for cr in frogs_settings['channel_rates'])


        for i in range(len(channel_rates)):
            spawner = self.Spawner(channel_rates[i][0], channel_rates[i][1], copy(self.frog_timer))
            task = (asyncio.create_task(spawner.start(minutes=spawner.random_spawn_time())))
            spawner.set_first_spawn_task(task)
            self._frogs_spawner.append(spawner)

        # Message
        embed = make_simple_embed('Frogs will now start spawning in the following channels...', '\n'.join(ch[0].mention for ch in channel_rates))    
        embed.set_thumbnail(url='https://i.imgur.com/IR5htIF.png')
        await ctx.send(embed=embed)

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)

    
    @frogs.command()
    @commands.has_guild_permissions(manage_guild=True) 
    async def stop(self, ctx):
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        frogs_settings = guild_conf['frogs']

        if not frogs_settings['op']:
            await ctx.send('Frogs were never spawning to begin with!')
            return

        frogs_settings['op'] = False

        while len(self._frogs_spawner) != 0:
            spawner = self._frogs_spawner.pop()
            spawner.stop()

        await ctx.send('Frogs have stopped spawning...')

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)

    
    @frogs.command()
    @commands.has_guild_permissions(manage_guild=True) 
    async def rates(self, ctx, new_rate:float, channel=None):
        if not channel:
            channel = ctx.channel

        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        frogs_settings = guild_conf['frogs']

        channels, rates = zip(*frogs_settings['channel_rates'])
        rates = list(rates)

        if channel.id not in channels:
            await ctx.send('Channel is not registered!')
            return

        for i in range(len(channels)):
            if channel.id == channels[i]:
                old_rate = rates[i]
                rates[i] = new_rate
                break

        frogs_settings['channel_rates'] = list(zip(channels, rates))
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)

        await ctx.send('{ch} rates have been changed from **`{old}`** to **`{new}`** minutes.'.format(ch=channel.mention, old=old_rate, new=new_rate))



    @tasks.loop(minutes=_SPAWNRATE_DEFAULT)
    async def frog_timer(self, spawner):
        await self.spawn(spawner.get_channel())
        spawner.change_interval_random()

    
    @frogs.command()
    @commands.has_guild_permissions(manage_guild=True) 
    async def register(self, ctx, *, channel:discord.TextChannel = None):
        if not channel:
            channel = ctx.channel

        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        frogs_settings = guild_conf['frogs']

        for ch_ra in frogs_settings['channel_rates']:
            if ch_ra[0] == channel.id:        
                await channel.send('{ch} is already spawning frogs!'.format(ch=channel.mention))
                return

        frogs_settings['channel_rates'].append([channel.id, _SPAWNRATE_DEFAULT])
        await channel.send('{ch} will now spawn frogs.'.format(ch=channel.mention))
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)


    @frogs.command()
    @commands.has_guild_permissions(manage_guild=True) 
    async def unregister(self, ctx, *, channel:discord.TextChannel = None):
        if not channel:
            channel = ctx.channel

        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        frogs_settings = guild_conf['frogs']

        for ch_ra in frogs_settings['channel_rates']:
            if ch_ra[0] == channel.id:
                frogs_settings['channel_rates'].remove(ch_ra)
                await channel.send('{ch} will no longer spawn frogs.'.format(ch=channel.mention))
                db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)
                return
        
        await channel.send('{ch} was never spawning frogs to begin with!'.format(ch=channel.mention))


    async def spawn(self, channel: discord.TextChannel):
        msg_spawn = await channel.send(_SPAWN)
        await msg_spawn.add_reaction(_REACT)
        
        def check(reaction, user):
            return (reaction.message.id == msg_spawn.id and
                str(reaction.emoji) == _REACT and
                user != self.bot.user)

        try:
            reaction, catcher = await self.bot.wait_for('reaction_add', check=check, timeout=_TIMEOUT)

            catcher_data = db_user_interface.fetch(self.bot.db_user, catcher.id)
            catcher_data['frogs'] += 1

            embed = discord.Embed(
                        title=_CONGRATS, 
                        description=_DELTA + '\n\n' + _RESULT.format(old=catcher_data['frogs']-1,new=catcher_data['frogs']),
                        color=0x9edbf7)
            
            embed.set_thumbnail(url=_URL_CAUGHT)
            embed.set_footer(text=catcher.display_name, icon_url=catcher.avatar_url)
            

            await msg_spawn.delete()
            await channel.send(content=catcher.mention, embed=embed)

            db_user_interface.write(self.bot.db_user, catcher.id, catcher_data)
        
        except asyncio.TimeoutError:
            await msg_spawn.delete()
            # await channel.send(_FAIL)

    
    @frogs.command()
    async def consume(self, ctx, count=1):
        consumer = ctx.message.author
        consumer_data = db_user_interface.fetch(self.bot.db_user, consumer.id)
        
        if count > consumer_data['frogs']:
            await ctx.send('You do not have enough frogs! You only have **`{}`**.'.format(consumer_data['frogs']))
            return
        elif count < 1:
            return

        def check(message):
            if message.author == consumer and message.channel == ctx.channel:
                if message.content.lower() in ['y', 'n']:
                    return True
            
            return False 

        exp_factor = consumer_data['exp_factor']
        if count * _EXP_FACTOR_PER_FROG + exp_factor > _EXP_FACTOR_CAP:
            old_count = count
            if exp_factor > 1:
                count = (_EXP_FACTOR_CAP - (exp_factor - 1)) / _EXP_FACTOR_PER_FROG
            else:
                count = int(_EXP_FACTOR_CAP / _EXP_FACTOR_PER_FROG)
            confirmation = await ctx.send('Consuming **`{old:d}`** number of frogs will put you over the experience factor cap (**`x{cap}`**). Would you like to instead consume **`{count:d}`** frog(s) for the cap?\nPlease type **`Y`** or **`N`**'.format(old=old_count, cap=_EXP_FACTOR_CAP, count=count))
        
        else:
            confirmation = await ctx.send('Are you sure you\'d like you consume `{count}` frog(s) for a total of `x{factor:.2f}` experience factor for the next {sec} seconds?\nPlease type **`Y`** or **`N`**'.format(count=count, factor=exp_factor+count*_EXP_FACTOR_PER_FROG, sec=30))

        try:
            message = await self.bot.wait_for('message', check=check, timeout=7)
            
            if message.content.lower() == 'n':
                await confirmation.add_reaction('❌')
                return
            
            consumer_data['frogs'] -= count
            exp_factor += count * _EXP_FACTOR_PER_FROG
            expiration = Timer(self.factor_expire, seconds=30)
            await expiration.start(consumer, count)

            await ctx.send('Frog(s) have been consumed. You\'re now at an experience factor of **`x{factor:.2f}`**.'.format(factor=exp_factor))

            consumer_data['exp_factor'] = exp_factor
            db_user_interface.write(self.bot.db_user, consumer.id, consumer_data)
        
        except asyncio.TimeoutError:
            await confirmation.add_reaction('❌')


    async def factor_expire(self, consumer, count):
        consumer_data = db_user_interface.fetch(self.bot.db_user, consumer.id)
        consumer_data['exp_factor'] -= count * _EXP_FACTOR_PER_FROG

        db_user_interface.write(self.bot.db_user, consumer.id, consumer_data)


def setup(bot):
    bot.add_cog(Frogs(bot))