import sys, warnings

from collections import defaultdict

import discord
from discord.ext import commands, tasks
import db_user_interface, db_guild_interface
import asyncio
from utility import make_simple_embed, Timer
from random import uniform
from copy import copy

# Later, read these vars from some db on startup
_SPAWNRATE_DEFAULT = 3.5 #minutes
_SPAWNRATE_SWING = .1 #within 20% offsets
_TIMEOUT = 5

# -----------
#
# The elements used on frog spawn
# Initial Spawning
_SPAWN = '<:cirnoFrog:695126166301835304>'
_REACT = '<:cirnoNet:752290769712316506>'
_CAPTURED = '<:cirnoFrog:695126166301835304>'

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
_EXP_FACTOR_BUFF_DURATION_NORMAL = 30 #minutes


class Frogs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._frogs_spawner = defaultdict(list) # guild_id : [spawner]

        db_guild_interface.reset_frog_active_all(self.bot.db_guild)

    
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
        def __init__(self, guild_id: int, channel_id: int, base_rate: int, spawner_loop, cog):
            self.guild_id = guild_id
            self.channel_id = channel_id
            self._base_rate = base_rate
            self._spawner = spawner_loop
            self._task_delay_start = None
            self._cog = cog

        async def start(self, seconds=0, minutes=0):
            async def delay_start(minutes):
                self.debug_frog_spawns_in(minutes)
                await asyncio.sleep(minutes*60 + seconds)
                self.change_interval(random=True)
                self._spawner.start(self)
            
            delay_minutes = self.get_random_spawn_time()
            self.change_interval(minutes=delay_minutes)
            self._task_delay_start = asyncio.create_task(delay_start(self.get_random_spawn_time()))
            
        def stop(self):
            self._task_delay_start.cancel()
            self._spawner.cancel()

        def set_base_rate(self, rate):
            if rate < 0:
                rate = 1
            
            self._base_rate = rate

        def change_interval(self, random=False, minutes=0, debug=False):
            self._spawner.change_interval(seconds=_TIMEOUT, minutes=self.get_random_spawn_time(debug=debug) if random == True else minutes)

        def get_random_spawn_time(self, debug=False):
            delay = _SPAWNRATE_SWING*self._base_rate*uniform(-1, 1) + self._base_rate
            
            if debug:
                self.debug_frog_spawns_in(delay)
            return delay

        def debug_frog_spawns_in(self, minutes):
            print('>> Spawning frog in {:.2f} minutes ({:2f} seconds) in {ch}'.format(minutes/60, minutes*60, ch=self.channel_id))

    
    @tasks.loop(minutes=_SPAWNRATE_DEFAULT)
    async def frog_timer(self, spawner):
        await self.spawn(spawner.channel_id, spawner.guild_id)
        # print('\nloop has finished the spawn function, will now change interval')
        spawner.change_interval(random=True, debug=True)


    @commands.group(aliases=['frog'], invoke_without_command=True)
    async def frogs(self, ctx, user:discord.Member=None):
        '''
        Shows everything about you related to frogs.

        Provide a user to see their stats instead.
        '''
        if ctx.invoked_subcommand is None:
            if user == None:
                user = ctx.message.author

            user_data = db_user_interface.fetch(self.bot.db_user, user.id)
            sorted_users = db_user_interface.fetch_all(self.bot.db_user)
            sorted_users = list(filter(lambda user: user['frogs_normal'] > 0, sorted_users))
            sorted_users.sort(key=lambda user: user['frogs_normal'], reverse=True)

            sorted_users_ids = list(map(lambda user: user['id'], sorted_users))
            if user_data['frogs_normal'] == 0:
                placement = -1
            else:
                placement = sorted_users_ids.index(user.id)

            title = '{user}\'s Capture Card'.format(user=user.display_name)

            possession = user_data['frogs_normal']
            lifetime = user_data['frogs_lifetime']

            if lifetime < possession:
                lifetime = possession
                user_data['frogs_lifetime'] = user_data['frogs_normal']
                db_user_interface.write(self.bot.db_user, user.id, user_data)

            data = 'Lifetime Captures: **`{lifetime}`**\nCurrently in possession of **`{count}`** frogs.'.format(lifetime=lifetime, count=possession)

            display = _CAPTURED * (possession // 10)    # Not used at the moment

            if placement == -1:
                report = ''
                compare = ''
            else:
                report = '{user} are ranked **`#{place}`** out of **`{total}`**!'.format(user='You' if ctx.message.author == user else user.mention, place=placement + 1, total=len(sorted_users))

                compare = '```py\n{place:8}{mode:<8}{user:20}\n'.format(place='Place', mode='Frogs', user='User')
                for i in range(max(0, placement-2), min(placement+3, len(sorted_users))):
                    if i == placement:
                        compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place='@'+str(i+1), count=int(sorted_users[i]['frogs_normal']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                    elif i%2:
                        compare += '{place:<8}{count:<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['frogs_normal']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                    else:
                        compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['frogs_normal']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                compare += '```'

            desc = data + '\n\n' + report + '\n' + compare

            embed = make_simple_embed(title, desc)
            embed.set_thumbnail(url=user.avatar_url)
            
            await ctx.send(embed=embed)


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

        if frogs_settings['active']:
            await ctx.send('Frogs are already spawning!')
            return
    
        frogs_settings['active'] = True

        channel_ids, rates = zip(*frogs_settings['channel_rates'])


        for i in range(len(channel_ids)):
            spawner = self.Spawner(ctx.guild.id, channel_ids[i], rates[i], copy(self.frog_timer), self)
            await spawner.start()
            self._frogs_spawner[ctx.guild.id].append(spawner)

        # Message
        embed = make_simple_embed('Frogs will now start spawning in the following channels...', '\n'.join(ctx.guild.get_channel(id).mention for id in channel_ids))    
        embed.set_thumbnail(url='https://i.imgur.com/IR5htIF.png')
        await ctx.send(embed=embed)

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)

    
    @frogs.command()
    @commands.has_guild_permissions(manage_guild=True) 
    async def stop(self, ctx):
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        frogs_settings = guild_conf['frogs']

        if not frogs_settings['active']:
            await ctx.send('Frogs were never spawning to begin with!')
            return

        frogs_settings['active'] = False

        while len(self._frogs_spawner[ctx.guild.id]) != 0:
            spawner = self._frogs_spawner[ctx.guild.id].pop()
            spawner.stop()

        del self._frogs_spawner[ctx.guild.id]

        await ctx.send('Frogs have stopped spawning...')

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)

    
    @frogs.command(aliases=['rate'])
    @commands.has_guild_permissions(manage_guild=True) 
    async def rates(self, ctx, new_rate:float=None, channel:discord.TextChannel=None):
        if new_rate == None:
            guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
            frogs_settings = guild_conf['frogs']
            
            channels, rates = zip(*frogs_settings['channel_rates'])

            if len(channels) == 0:
                ctx.send('No channels are registered...')

            desc = ''

            for i in range(len(channels)):
                desc += ctx.guild.get_channel(channels[i]).mention + ' -> ' + str(rates[i]) + '\n'
            
            await ctx.send(desc)
            return

        if not channel:
            channel = ctx.channel
        
        channel_id = channel.id

        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        frogs_settings = guild_conf['frogs']

        channels, rates = zip(*frogs_settings['channel_rates'])
        rates = list(rates) #because it's in a tuple and this immutable
        if channel_id not in channels:
            await ctx.send('Channel is not registered!')
            return

        for i in range(len(channels)):
            if channel_id == channels[i]:
                old_rate = rates[i]
                rates[i] = new_rate
                break

        for spawner in self._frogs_spawner[ctx.guild.id]:
            if spawner.channel_id == channel_id:
                spawner.set_base_rate(new_rate)
                spawner.stop()
                await spawner.start()
                

        frogs_settings['channel_rates'] = list(zip(channels, rates))
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)

        await ctx.send('{ch} rates have been changed from **`{old}`** to **`{new}`** minutes.'.format(ch=channel.mention, old=old_rate, new=new_rate))

    
    @frogs.command()
    @commands.has_guild_permissions(manage_guild=True) 
    async def register(self, ctx, channel:discord.TextChannel = None, rate=_SPAWNRATE_DEFAULT):
        if not channel:
            channel = ctx.channel

        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        frogs_settings = guild_conf['frogs']

        for ch_ra in frogs_settings['channel_rates']:
            if ch_ra[0] == channel.id:        
                await ctx.send('{ch} is already spawning frogs!'.format(ch=channel.mention))
                return

        if frogs_settings['active']:
            spawner = self.Spawner(ctx.guild.id, channel, rate, copy(self.frog_timer), self)
            await spawner.start()
            self._frogs_spawner[ctx.guild.id].append(spawner)

        frogs_settings['channel_rates'].append([channel.id, rate])        
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)

        await ctx.send('{ch} will now spawn frogs around some rate of **`1`** every **`{rate}`** minutes.'.format(ch=channel.mention, rate=rate))


    @frogs.command()
    @commands.has_guild_permissions(manage_guild=True) 
    async def unregister(self, ctx, *, channel:discord.TextChannel = None):
        if not channel:
            channel = ctx.channel

        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        frogs_settings = guild_conf['frogs']
        
        if frogs_settings['active']:
            for spawner in self._frogs_spawner[ctx.guild.id]:
                if spawner.get_channel() == channel:
                    spawner.stop()
                    self._frogs_spawner[ctx.guild.id].remove(spawner)
                    
                    if len(self._frogs_spawner[ctx.guild.id]) == 0:
                        frogs_settings['active'] = False
                    
                    break
        
        for ch_ra in frogs_settings['channel_rates']:
            if ch_ra[0] == channel.id:
                frogs_settings['channel_rates'].remove(ch_ra)
                db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)
                await ctx.send('{ch} will no longer spawn frogs.'.format(ch=channel.mention))
                return

        await ctx.send('{ch} was never spawning frogs to begin with!'.format(ch=channel.mention))


    async def spawn(self, channel: discord.TextChannel, guild_id = None):
        if not isinstance(channel, discord.TextChannel):
            channel = self.bot.get_guild(guild_id).get_channel(channel)

        msg_spawn = await channel.send(_SPAWN)
        await msg_spawn.add_reaction(_REACT)
        
        def check(reaction, user):
            return (reaction.message.id == msg_spawn.id and
                str(reaction.emoji) == _REACT and
                not user.bot)

        try:
            reaction, catcher = await self.bot.wait_for('reaction_add', check=check, timeout=_TIMEOUT)

            catcher_data = db_user_interface.fetch(self.bot.db_user, catcher.id)            
            catcher_data['frogs_lifetime'] += 1
            catcher_data['frogs_normal'] += 1
            
            # Workaround to update lifetime on implementation
            if catcher_data['frogs_lifetime'] < catcher_data['frogs_normal']:
                catcher_data['frogs_lifetime'] = catcher_data['frogs_normal']

            embed = discord.Embed(
                        title=_CONGRATS, 
                        description=_DELTA + '\n\n' + _RESULT.format(old=catcher_data['frogs_normal']-1,new=catcher_data['frogs_normal']),
                        color=0x9edbf7)
            
            embed.set_thumbnail(url=_URL_CAUGHT)
            embed.set_footer(text=catcher.display_name, icon_url=catcher.avatar_url)
            
            await msg_spawn.delete()
            await channel.send(content=catcher.mention, embed=embed, delete_after=20)

            db_user_interface.write(self.bot.db_user, catcher.id, catcher_data)
        
        except asyncio.TimeoutError:
            await msg_spawn.delete()
            # await channel.send(_FAIL)

    
    @frogs.command()
    async def consume(self, ctx, count=1):
        '''
        Consumes a the specified amount of frogs. 
        
        Consuming frogs will give you additional experience factor, greatly increasing the amount of experience you get permessage sent.
        '''
        consumer = ctx.message.author
        consumer_data = db_user_interface.fetch(self.bot.db_user, consumer.id)
        consumer_frogs = consumer_data['frogs_normal']
        consumer_factor = consumer_data['exp_factor']

        if consumer_factor >= 1 + _EXP_FACTOR_CAP:
            embed = make_simple_embed('', 'You\'re already at the experience factor cap of **`x{cap}`**!'.format(cap=1+_EXP_FACTOR_CAP))
            await ctx.send(content=consumer.mention, embed=embed)
            return
        
        if count > consumer_frogs:
            embed = make_simple_embed('', 'You do not have enough frogs! You only have **`{count}`**!'.format(count=consumer_frogs))
            await ctx.send(content=consumer.mention, embed=embed)
            return
        
        if count <= 0:
            return

        # If consuming {count} many frogs would put us over the exp cap...
        if count * _EXP_FACTOR_PER_FROG + consumer_factor > 1 + _EXP_FACTOR_CAP:
            old_count = count
            count = int((_EXP_FACTOR_CAP - (consumer_factor - 1)) / _EXP_FACTOR_PER_FROG)
            
            topic = 'Consuming **`{old}`** number of frogs will put you over the experience factor cap (**`x{cap}`**). Would you like to instead consume **`{count}`** frog(s) for the cap?'.format(old=old_count, cap=_EXP_FACTOR_CAP+1, count=int(count))
            effects = 'Resulting frogs\n**`{old_frogs}`**->**`{new_frogs}`**\nResulting experience factor\n**`x{old_fact:.2f}`**->**`x{new_fact:.2f}`**'.format(old_frogs=consumer_frogs, new_frogs=consumer_frogs-count, old_fact=consumer_factor, new_fact=consumer_factor+count*_EXP_FACTOR_PER_FROG)
            duration = '*This buff will last {long} minutes.*'.format(long=_EXP_FACTOR_BUFF_DURATION_NORMAL)

            desc = topic + '\n\n' + effects + '\n\n' + duration
            confirmation_embed = make_simple_embed('Confirmation', desc)
        else:
            topic = '**Are you sure you\'d like you consume `{count}` frog(s) with the following effects?**'.format(count=count)
            effects = 'Resulting frogs\n**`{old_frogs}`**->**`{new_frogs}`**\nResulting experience factor\n**`x{old_fact:.2f}`**->**`x{new_fact:.2f}`**'.format(old_frogs=consumer_frogs, new_frogs=consumer_frogs-count, old_fact=consumer_factor, new_fact=consumer_factor+count*_EXP_FACTOR_PER_FROG)
            duration = '*This buff will last {long} minutes.*'.format(long=_EXP_FACTOR_BUFF_DURATION_NORMAL)

            desc = topic + '\n\n' + effects + '\n\n' + duration
            confirmation_embed = make_simple_embed('Confirmation', desc)
        
        confirmation_embed.set_thumbnail(url='https://i.imgur.com/ybxI7pu.png')
        confirmation = await ctx.send(embed=confirmation_embed)
        await confirmation.add_reaction('❌')
        await confirmation.add_reaction('✅')
        try:
            def check(reaction, user):
                if user.id == consumer.id and reaction.message.id == confirmation.id:
                    if reaction.emoji in ['❌', '✅']:
                        return True
            
                return False 
            
            reaction, consumer = await self.bot.wait_for('reaction_add', check=check, timeout=10)
            
            if reaction.emoji == '❌':
                await confirmation.delete()
                return
            
            # Applying counts and error checking
            consumer_frogs -= count
            if consumer_frogs < 0:
                warnings.warn('Consumer {consumer}\'s frog count resulted in {old} -> {new} frogs. Defaulting to 0...'.format(consumer=consumer, old=consumer_frogs-count, new=consumer_frogs), RuntimeWarning)
                consumer_frogs = 0
            
            consumer_factor += count * _EXP_FACTOR_PER_FROG
            if consumer_factor > 1 + _EXP_FACTOR_CAP:
                warnings.warn('Consumer {consumer}\'s exp factor resulted in {old} -> {new}. They ate {count} frog(s). Defaulting to x2.5...'.format(consumer=consumer, old=consumer_factor - count * _EXP_FACTOR_PER_FROG, new=consumer_factor, count=count), RuntimeWarning)
                consumer_factor = 2.5
            
            expiration = Timer(self.factor_expire, minutes=30)
            await expiration.start(consumer, count)

            confirmation_embed.title = 'Frog(s) have been consumed'
            confirmation_embed.description = effects + '\n\n' + duration
            confirmation_embed.set_thumbnail(url='https://i.imgur.com/kCHjymJ.png')
            await confirmation.edit(content=consumer.mention, embed=confirmation_embed)

            # Applying values to data structure and writing
            consumer_data['exp_factor'] = consumer_factor
            consumer_data['frogs_normal'] = consumer_frogs
            db_user_interface.write(self.bot.db_user, consumer.id, consumer_data)
        
        except asyncio.TimeoutError:
            await confirmation.delete()


    async def factor_expire(self, consumer, count):
        consumer_data = db_user_interface.fetch(self.bot.db_user, consumer.id)
        consumer_factor = consumer_data['exp_factor']

        consumer_factor -= count * _EXP_FACTOR_PER_FROG
        if consumer_factor < 0:
            warnings.warn('Frog decayed on {consumer} which resulted in an exp factor {old}->{new}. Defaulting to x1...'.format(consumer=consumer, old=consumer_factor+count*_EXP_FACTOR_PER_FROG, new=consumer_factor), RuntimeWarning)
            consumer_factor = 1
        
        consumer_data['exp_factor'] = consumer_factor
        db_user_interface.write(self.bot.db_user, consumer.id, consumer_data)


def setup(bot):
    bot.add_cog(Frogs(bot))