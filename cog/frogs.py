'''
Handles all of the frog mechanics.

Frog can spawn within any channel in accordance to that guild's frog settings. When a frog spawns, it will roll to check if it will actually spawn or not.
This roll must be above _ACTIVITY_UPPER_BOUND for the frog to actually spawn. If it rolls lower the frog will not spawn and another timer will begin for it's
next spawn.

Frogs are scared of talking users. If users are actively talking in the server at all, there will be less of a chance of them to spawn. Once
_ACTIVITY_MESSAGES_UNTIL_UPPER_BOUND messages have been sent in the last _ACTIVITY_TIMEOUT minutes, the roll for frogs must be above _ACTIVITY_UPPER_BOUND for
the frog the spawn. The reasoning for this was to promote talking when there already exists talking. When there isn't much talking users are free to
catch frogs as they want.

When a frog spawns(?) (or after it is captured?) it will start a timer that will spawn another from when it runs out.
'''

import sys, warnings

from collections import defaultdict
from random import choice, random

import discord
from discord.ext import commands, tasks
import db_user_interface, db_guild_interface
import asyncio
from utility import make_simple_embed_t, Timer, PARSE_CLASS_VAR
from random import uniform, random
from copy import copy
import customs.cog

# Later, read these vars from some db on startup
_SPAWNRATE_DEFAULT = 7.0 #minutes
_SPAWNRATE_SWING = .1 #within % offsets
_TIMEOUT = 120   # seconds before frog disappears
# og 7, .1, 120


################################################################
# The elements used on frog spawn
################################################################
# Initial Spawning
_SPAWN = '<:cirnoFrog:695126166301835304>'
_REACT = '<:cirnoNet:752290769712316506>'
_CAPTURED = '<:cirnoFrog:695126166301835304>'

# Successful catch
_CONGRATS = 'Congrats on your catch!'
_DELTA = '+1 to froggies'
_RESULT = '**Total froggies: `{old}` -> `{new}`**'
_URL_CAUGHT = 'https://i.imgur.com/uwPIHMv.png'
_TIP = 'TIP: Consume frogs with c!frogs consume '

# Failure
_FAIL = 'You were too slow!'

################################################################
# Consumption of frogs
################################################################
_EXP_FACTOR_PER_FROG = .1
_EXP_FACTOR_CAP = 0.5
_EXP_FACTOR_BUFF_DURATION_NORMAL = 30 #minutes

################################################################
# Activity-based spawns
################################################################
_ACTIVITY_CONCURRENT_MEMBERS = 2 #at least X members
_ACTIVITY_MESSAGES_UNTIL_UPPER_BOUND = 100 #messages until upper bound
_ACTIVITY_UPPER_BOUND = 0.6 #what rng roll has to be above to spawn a frog
_ACTIVITY_FACTOR = 2
_ACTIVITY_TIMEOUT = 15 #minutes
_ACTIVITY_FUNCTION = lambda count: _ACTIVITY_UPPER_BOUND*(count/_ACTIVITY_MESSAGES_UNTIL_UPPER_BOUND)**_ACTIVITY_FACTOR


################################################################
# April Fools
################################################################
_FOOLS_FROG = [
    "<:cirnoCursedPogFrog:780634396699918376>",
    "'Sorry, I know you were trying to catch your frog, but Soru took 'em!' <:cirnoCursedSugoiWow:780633607123107862>",
    "https://tenor.com/view/dance-moves-dancing-singer-groovy-gif-17029825",
    "https://tenor.com/view/frog-pat-head-pet-froge-gif-17800229",
    "https://cdn.discordapp.com/attachments/826587217438441552/826588787492388914/cirnoBakaFrog.png",
    "https://tenor.com/view/fortnite-thanos-orange-justice-dancing-dance-gif-16354935 thanos took your frog <:cirnoPfft:695126168373952562>",
    "https://cdn.discordapp.com/attachments/826587217438441552/826589658091487272/1617144672969.png",
    "https://cdn.discordapp.com/attachments/826587217438441552/826594308978376744/Cute-angry-frog-696x358.jpg",
    "https://cdn.discordapp.com/attachments/826587217438441552/826594468986617905/5c7cd1159fa339e417bffb9e616c9a08.jpg",
    "https://cdn.discordapp.com/attachments/826587217438441552/826597037863993354/frog_suwako_hat.png",
    "https://tenor.com/view/touhou-fumo-suwako-jump-bounce-gif-18089454",
    "https://media4.giphy.com/media/Wrh8aL75aj4uZwuqta/200.gif",
    "<:cirnoFrogClassy:706228020251197490>",
    "<:cirnoFrogBox:796194831226503179>",
    "https://tenor.com/view/touhou-suwako-anime-gif-8780783",
    "https://tenor.com/view/happy-dance-frog-dancing-excited-toad-gif-7628390",
    "Cirno fumo was here. <:cirnoFumo:755178677603401879>",
    "you thought it was frog, but it was me, dio! https://tenor.com/view/dio-jojo-anime-cartoon-japanese-gif-7432836",
    "<:cirnoCursedPogFrog:780634396699918376> <:cirnoNom:695126168508301353>",
    "https://tenor.com/bblhd.gif",
    "https://tenor.com/view/bababooey-gif-19046935",
    "https://tenor.com/view/pepe-punch-hit-meme-frog-gif-14157444",
    "https://tenor.com/view/funny-frog-frog-meme-vibe-pee-mode-gif-17420275",
    "https://tenor.com/view/im-cheezin-bright-smiles-got-teeth-frog-smile-frog-gif-12039847",
    "https://tenor.com/view/pepe-pepe-the-frog-sad-pepe-crying-tears-gif-7939264",
    "https://tenor.com/view/frog-drummer-drums-drumming-musical-instrument-gif-17694215",
    "https://tenor.com/view/touhou-cirno-fumo-plush-ice-gif-18790493",
    '"Not only you capture le frog, but you also froze it!" <:cirnoShookWoke:695126170466910268>',
    'https://tenor.com/view/hi-reimu-cirno-silly-cirno-kfc-cirno-touhou-gif-20796926',
    'https://tenor.com/view/toad-frog-eat-gif-16894804',
    'your frog has turned on you http://33.media.tumblr.com/9afdac240962d937c6240ce50cf36994/tumblr_n9u7jmDDdt1s9ab4to1_400.gif',
    'https://media.tenor.com/images/c869633d539f497e7375657668e084a4/tenor.gif?ctx=share',
    'https://media.tenor.com/images/c4537c60c4f201305adc3fae8b9a536a/tenor.gif?ctx=share',
    'https://tenor.com/view/on-pepe-frog-in-ugly-gif-14404607',
    'https://tenor.com/view/run-smokey-use-your-legs-hotfoot-gif-15544418 "Wrong frog! Run! <:cirnoSpooketh:695126170575962172>"',
    'https://giphy.com/gifs/kermit-vqj0SziyUHmnK',
    'https://tenor.com/view/roblox-funny-oof-gaming-gif-17036380'
]


class Frogs(customs.cog.Cog):
    # One spawner per channel. Each spawner is responsible for it's set channel.
    _frogs_spawner_ = defaultdict(list) # guild_id : [spawner]

    # Contains the current activity in a channel. This is used to determine if a frog will spawn or not.
    # Frogs are scared of active users talking.
    _activity_ = defaultdict(lambda: defaultdict(list)) # guild_id : member_id : timer

    def __init__(self, bot, data:dict = None):
        super().__init__(bot)
        if self._first_load_:
            db_guild_interface.reset_frog_active_all(self.bot.db_guild)
    

    # async def cog_command_error(self, ctx, error):
    #     # This statement checks to see if the command has a local error handler,
    #     # and if so, don't run the cog error handler
    #     if hasattr(ctx.command, 'on_error'):
    #         return

    #     if isinstance(error, commands.MissingPermissions):
    #         await ctx.send('You are missing the following permissions: `{}`'.format(', '.join(error.missing_perms)))
    #     else:
    #         print('Ignoring exception from command {}:'.format(ctx.command), file=sys.stderr)
    #         raise(error)

    @commands.Cog.listener()
    async def on_message(self, message):
        '''Keep a log of recent activities of users.'''
        timer = Timer(self.activity_decay, seconds=3)
        guild_id = message.guild.id
        member_id = message.author.id

        timer.start(guild_id, member_id, timer)
        self._activity_[guild_id][member_id].append(timer)


    def activity_decay(self, guild_id, member_id, timer):
        self._activity_[guild_id][member_id].remove(timer)
        if not len(self._activity_[guild_id][member_id]):
            del self._activity_[guild_id][member_id]


    class Spawner():
        '''
        Manages the frog spawns for a particular channel. It leverages discord.py's built in tasks.loop to automate looping the timer.
        '''
        def __init__(self, guild_id: int, channel_id: int, base_rate: int, spawner_loop, cog):
            self.guild_id = guild_id
            self.channel_id = channel_id
            self._base_rate = base_rate
            self._spawner = spawner_loop
            self._task_delay_start = None
            self._cog = cog

        def start(self):
            async def delay_start(minutes):
                self.debug_frog_spawns_in(minutes)
                await asyncio.sleep(minutes*60)
                self.change_interval(random=True)
                self._spawner.start(self)
            
            # Manually have a pre-timer before spawning as tasks.loop does not support wait-in at the time of writing
            delay_minutes = self.get_random_spawn_time()
            self.change_interval(minutes=delay_minutes)
            self._task_delay_start = asyncio.create_task(delay_start(self.get_random_spawn_time()))
            
        def stop(self):
            self._task_delay_start.cancel()
            self._spawner.cancel()

        def set_wait(self, rate):
            '''How long to wait until spawning another frog.'''
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
        spawner.change_interval(random=True, debug=True)


    # --------------------------------------------
    # User Commands
    # --------------------------------------------
    @commands.group(aliases=['frog'], invoke_without_command=True)
    async def frogs(self, ctx, *, user:discord.Member=None):
        '''
        Shows everything about you related to frogs.

        Provide a user to see their stats instead.
        '''
        if ctx.invoked_subcommand is None:
            if user == None:
                user = ctx.message.author

            user_data = db_user_interface.fetch(self.bot.db_user, user.id)
            sorted_users = db_user_interface.fetch_all(self.bot.db_user)
            sorted_users = list(filter(lambda user: user['frogs_lifetime'] > 0, sorted_users))
            sorted_users.sort(key=lambda user: user['frogs_lifetime'], reverse=True)

            sorted_users_ids = list(map(lambda user: user['id'], sorted_users))
            if user_data['frogs_lifetime'] == 0:
                placement = -1
            else:
                placement = sorted_users_ids.index(user.id)

            title = '{user}\'s Capture Card'.format(user=user.display_name)

            possession = user_data['frogs_normal']
            lifetime = user_data['frogs_lifetime']

            data = 'Lifetime Captures: **`{lifetime}`**\nCurrently in possession of **`{count}`** frogs.'.format(lifetime=lifetime, count=possession)

            display = _CAPTURED * (possession // 10)    # Not used at the moment

            if placement == -1:
                report = ''
                compare = ''
            else:
                report = '{user} are ranked **`#{place}`** out of **`{total}`**!'.format(user='You' if ctx.message.author == user else user.mention, place=placement + 1, total=len(sorted_users))

                compare = '```py\n{place:8}{mode:<8}{user:20}\n'.format(place='Place', mode='Frogs', user='User')
                for i in range(max(0, placement-2), min(placement+3, len(sorted_users))):
                    try:
                        if i == placement:
                            compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place='@'+str(i+1), count=int(sorted_users[i]['frogs_lifetime']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                        elif i%2:
                            compare += '{place:<8}{count:<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['frogs_lifetime']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                        else:
                            compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['frogs_lifetime']), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                    except AttributeError:
                        if i == placement:
                            compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place='@'+str(i+1), count=int(sorted_users[i]['frogs_lifetime']), user=(await self.bot.fetch_user(sorted_users[i]['id'])).display_name)
                        elif i%2:
                            compare += '{place:<8}{count:<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['frogs_lifetime']), user=(await self.bot.fetch_user(sorted_users[i]['id'])).display_name)
                        else:
                            compare += '{place:.<8}{count:.<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i]['frogs_lifetime']), user=(await self.bot.fetch_user(sorted_users[i]['id'])).display_name)                
                compare += '```'

            desc = data + '\n\n' + report + '\n' + compare

            embed = make_simple_embed_t(title, desc)
            embed.set_thumbnail(url=user.avatar_url)
            
            await ctx.send(embed=embed)


    @frogs.command()
    @commands.is_owner()
    async def fspawn(self, ctx):
        '''Force a frog to spawn'''
        await self.spawn(ctx.channel, force=True)


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
            spawner.start()
            Frogs._frogs_spawner_[ctx.guild.id].append(spawner)

        # Message
        embed = make_simple_embed_t('Frogs will now start spawning in the following channels...', '\n'.join(ctx.guild.get_channel(id).mention for id in channel_ids))    
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

        while len(Frogs._frogs_spawner_[ctx.guild.id]) != 0:
            spawner = Frogs._frogs_spawner_[ctx.guild.id].pop()
            spawner.stop()

        del Frogs._frogs_spawner_[ctx.guild.id]

        await ctx.send('Frogs have stopped spawning...')

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)

    
    @frogs.command(aliases=['rate'])
    @commands.has_guild_permissions(manage_guild=True) 
    async def rates(self, ctx, new_rate:float=None, channel:discord.TextChannel=None):
        '''
        Make adjustments to this wait time for the frog spawns in this channel.
        '''
        if new_rate == None:
            guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
            frogs_settings = guild_conf['frogs']
            
            try:
                channels, rates = zip(*frogs_settings['channel_rates'])
            except ValueError as e:
                await ctx.send('No channels are registered...')
                return

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

        for spawner in Frogs._frogs_spawner_[ctx.guild.id]:
            if spawner.channel_id == channel_id:
                spawner.set_wait(new_rate)
                spawner.stop()
                spawner.start()
                

        frogs_settings['channel_rates'] = list(zip(channels, rates))
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)

        await ctx.send('{ch} rates have been changed from **`{old}`** to **`{new}`** minutes.'.format(ch=channel.mention, old=old_rate, new=new_rate))

    
    @frogs.command()
    @commands.has_guild_permissions(manage_guild=True) 
    async def register(self, ctx, channel:discord.TextChannel=None, rate=_SPAWNRATE_DEFAULT):
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
            spawner.start()
            Frogs._frogs_spawner_[ctx.guild.id].append(spawner)

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
            for spawner in Frogs._frogs_spawner_[ctx.guild.id]:
                if spawner.channel_id == channel:
                    spawner.stop()
                    Frogs._frogs_spawner_[ctx.guild.id].remove(spawner)
                    
                    if len(Frogs._frogs_spawner_[ctx.guild.id]) == 0:
                        frogs_settings['active'] = False
                    
                    break
        
        for ch_ra in frogs_settings['channel_rates']:
            if ch_ra[0] == channel.id:
                frogs_settings['channel_rates'].remove(ch_ra)
                db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)
                await ctx.send('{ch} will no longer spawn frogs.'.format(ch=channel.mention))
                return

        await ctx.send('{ch} was never spawning frogs to begin with!'.format(ch=channel.mention))


    async def spawn(self, channel: discord.TextChannel, guild_id = None, force=False):
        '''Spawn the frog and roll of it will actually spawn. Called internally.'''
        if not isinstance(channel, discord.TextChannel):
            channel = self.bot.get_guild(guild_id).get_channel(channel)

        if len(self._activity_[channel.guild.id]) >= _ACTIVITY_CONCURRENT_MEMBERS:
            count = sum(len(recent_messages) for recent_messages in self._activity_[channel.guild.id].values())
            roll = random()
            if roll < min(_ACTIVITY_UPPER_BOUND, _ACTIVITY_FUNCTION(count)):
                return

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
            embed.set_footer(text=_TIP, icon_url=catcher.avatar_url)
            
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

        This is planned to be deprecated to an extent... need more thought on it
        '''
        consumer = ctx.message.author
        consumer_data = db_user_interface.fetch(self.bot.db_user, consumer.id)
        consumer_frogs = consumer_data['frogs_normal']
        consumer_factor = consumer_data['exp_factor']

        if consumer_factor >= 1 + _EXP_FACTOR_CAP:
            embed = make_simple_embed_t('', 'You\'re already at the experience factor cap of **`x{cap}`**!'.format(cap=1+_EXP_FACTOR_CAP))
            await ctx.send(content=consumer.mention, embed=embed)
            return
        
        if count > consumer_frogs:
            embed = make_simple_embed_t('', 'You do not have enough frogs! You only have **`{count}`**!'.format(count=consumer_frogs))
            await ctx.send(content=consumer.mention, embed=embed)
            return
        
        if count <= 0:
            return

        # If consuming {count} many frogs would put us over the exp cap...
        if count * _EXP_FACTOR_PER_FROG + consumer_factor > 1 + _EXP_FACTOR_CAP:
            old_count = count
            count = int((_EXP_FACTOR_CAP - (consumer_factor - 1)) / _EXP_FACTOR_PER_FROG)
            
            topic = 'Consuming **`{old}`** number of frogs will put you over the experience factor cap (**`x{cap}`**). Would you like to instead consume **`{count}`** frog(s) for the cap?'.format(old=old_count, cap=_EXP_FACTOR_CAP+1, count=int(count))
            #effects = 'Resulting frogs\n**`{old_frogs}`**->**`{new_frogs}`**\nResulting experience factor\n**`x{old_fact:.2f}`**->**`x{new_fact:.2f}`**'.format(old_frogs=consumer_frogs, new_frogs=consumer_frogs-count, old_fact=consumer_factor, new_fact=consumer_factor+count*_EXP_FACTOR_PER_FROG)
            duration = '*This buff will last {long} minutes.*'.format(long=_EXP_FACTOR_BUFF_DURATION_NORMAL)
            
            effects = 'Resulting frogs\n**`{old_frogs}`**->**`{new_frogs}`**'.format(old_frogs=consumer_frogs, new_frogs=consumer_frogs-count)


            desc = topic + '\n\n' + effects + '\n\n' + duration
            confirmation_embed = make_simple_embed_t('Confirmation', desc)
        else:
            topic = '**Are you sure you\'d like you consume `{count}` frog(s) with the following effects?**'.format(count=count)
            #effects = 'Resulting frogs\n**`{old_frogs}`**->**`{new_frogs}`**\nResulting experience factor\n**`x{old_fact:.2f}`**->**`x{new_fact:.2f}`**'.format(old_frogs=consumer_frogs, new_frogs=consumer_frogs-count, old_fact=consumer_factor, new_fact=consumer_factor+count*_EXP_FACTOR_PER_FROG)
            duration = '*This buff will last {long} minutes.*'.format(long=_EXP_FACTOR_BUFF_DURATION_NORMAL)
                
            effects = 'Resulting frogs\n**`{old_frogs}`**->**`{new_frogs}`**'.format(old_frogs=consumer_frogs, new_frogs=consumer_frogs-count)


            desc = topic + '\n\n' + effects + '\n\n' + duration
            confirmation_embed = make_simple_embed_t('Confirmation', desc)
        
        confirmation_embed.set_thumbnail(url='https://i.imgur.com/ybxI7pu.png')
        deprecated_consume_msg = make_simple_embed_t("Consuming no longer apply experience factor", "Consume anyways?")
        confirmation = await ctx.send(embed=deprecated_consume_msg)
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
            expiration.start(consumer, count)

            confirmation_embed.title = 'Frog(s) have been consumed'
            confirmation_embed.description = effects# + '\n\n' + duration
            confirmation_embed.set_thumbnail(url='https://i.imgur.com/kCHjymJ.png')
            await confirmation.edit(content=consumer.mention, embed=confirmation_embed)

            # Applying values to data structure and writing
            consumer_data['exp_factor'] = consumer_factor
            consumer_data['frogs_normal'] = consumer_frogs
            db_user_interface.write(self.bot.db_user, consumer.id, consumer_data)
        
        except asyncio.TimeoutError:
            await confirmation.delete()

    
    @frogs.command(name='gift')
    async def gift(self, ctx, to:discord.Member, amount:int):
        if to == ctx.author:
            return

        type='frogs_normal'

        if amount <= 0:
            embed = make_simple_embed_t('Nice try', 'You can\'t steal frogs by negative gifting.')
            embed.set_thumbnail(url='https://cdn.discordapp.com/emojis/701138244712136774.png')
            await ctx.send(embed=embed)
            return

        user_from = db_user_interface.fetch(self.bot.db_user, ctx.message.author.id)
        user_to = db_user_interface.fetch(self.bot.db_user, to.id)

        if user_from[type] < amount:
            embed = make_simple_embed_t('ERROR', f'You do not have enough frogs!\nCurrently in possession of **`{user_from[type]}`** frogs.')
            embed.set_thumbnail(url='https://cdn.discordapp.com/emojis/755168446232264775.png')
            await ctx.send(embed=embed)
            return

        intro = f'You are going to give **`{amount}`** frogs to {to.mention}. Please confirm.'
        result = f'**Your** resulting frogs\n**`{user_from["frogs_normal"]}`** -> **`{user_from["frogs_normal"] - amount}`**\n{to.mention}\'s resulting frogs\n**`{user_to["frogs_normal"]}`** -> **`{user_to["frogs_normal"] + amount}`**'

        embed = make_simple_embed_t('Confirmation', '\n\n'.join([intro, result]))
        embed.set_thumbnail(url='https://i.imgur.com/ybxI7pu.png')
        confirmation = await self.request_confirmation(ctx, ctx.message.author, embed=embed)
        if confirmation:
            result = db_user_interface.users_trade_frogs(self.bot.db_user, ctx.author.id, to.id, amount)
            if result != 0:
                print(f">> ERROR: Gifting raised an error of {result}.")
                return

            embed.title = 'Frog(s) have been gifted'
            embed.description = f'{ctx.message.author.mention}\'s resulting frog count\n**`{user_from["frogs_normal"]}`** -> **`{user_from["frogs_normal"] - amount}`**\n{to.mention}\'s resulting frog count\n**`{user_to["frogs_normal"]}`** -> **`{user_to["frogs_normal"] + amount}`**'
            embed.set_thumbnail(url='https://cdn.discordapp.com/emojis/735692725520957481.gif')
            await confirmation.edit(content=' '.join([ctx.message.author.mention, to.mention]), embed=embed)


    async def request_confirmation(self, ctx, confirm_from:discord.Member, content=None, embed=None, timeout=10):
        def check(reaction, user):
            if user.id == confirm_from.id and reaction.message.id == confirmation.id:
                if reaction.emoji in ['❌', '✅']:
                    return True
        
            return False
        
        confirmation = await ctx.send(content, embed=embed)
        await confirmation.add_reaction('❌')
        await confirmation.add_reaction('✅')
        try:            
            reaction, _ = await self.bot.wait_for('reaction_add', check=check, timeout=timeout)
            
            if reaction.emoji == '❌':
                await confirmation.delete()
                return False
            
        except asyncio.TimeoutError:
            await confirmation.delete()
            return False
        
        return confirmation


    async def factor_expire(self, consumer, count):
        '''
        Called by timers defined under consume().
        '''
        consumer_data = db_user_interface.fetch(self.bot.db_user, consumer.id)
        consumer_factor = consumer_data['exp_factor']

        consumer_factor -= count * _EXP_FACTOR_PER_FROG
        if consumer_factor < 0:
            warnings.warn('Frog decayed on {consumer} which resulted in an exp factor {old}->{new}. Defaulting to x1...'.format(consumer=consumer, old=consumer_factor+count*_EXP_FACTOR_PER_FROG, new=consumer_factor), RuntimeWarning)
            consumer_factor = 1
        
        consumer_data['exp_factor'] = consumer_factor
        db_user_interface.write(self.bot.db_user, consumer.id, consumer_data)


    # ----------------------------------------------------------    
    # Statistics
    # ----------------------------------------------------------
    @commands.group(name='logfrogs', aliases=['logfrog'], invoke_without_command=True)
    @commands.is_owner()
    async def log_frogs(self, ctx):
        if ctx.invoked_subcommand is None:
            if self.frogs_logger.is_running():
                await ctx.send('I am currently logging frogs.')
            else:
                await ctx.send('I am currently **not** logging frogs.')
    

    @log_frogs.command(name='start')
    @commands.is_owner()
    async def log_frogs_start(self, ctx):
        try:
            self.frogs_logger.start()
        except RuntimeError:
            await ctx.send('Already logging frogs!')
            return

        await ctx.send('Will now start logging frogs over time...')

    
    @log_frogs.command(name='stop')
    @commands.is_owner()
    async def log_frogs_stop(self, ctx):
        if self.frogs_logger.is_running():
            self.frogs_logger.stop()
            await ctx.send('Will stop logging frogs...')
        else:
            await ctx.send('Was never logging to begin with...')


    @tasks.loop(minutes=60)
    async def frogs_logger(self):
        with open('frog_captures_log.csv', 'a') as log:
            all_users = db_user_interface.fetch_all(self.bot.db_user)

            log.write(','.join(str(user['frogs_lifetime']) for user in all_users) + '\n')


def setup(bot):
    bot.add_cog(Frogs(bot))