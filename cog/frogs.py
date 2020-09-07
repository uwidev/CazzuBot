import discord
from discord.ext import commands, tasks
import db_user_interface, db_guild_interface
import asyncio
from utility import make_simple_embed, timer
from random import uniform
from copy import copy

# Later, read these vars from some db on startup
_SPAWNRATE_DEFAULT = 5 #minutes
_SPAWNRATE_SWING = .35 #within 20% offsets
_TIMEOUT = 10

# -----------

# The elements used on frog spawn
# Initial Spawning
_SPAWN = '<:cirnoFrog:752291209535291453>'
_REACT = '<:cirnoNet:752290769712316506>'

# Successful catch
_CONGRATS = 'Congrats on your catch!'
_DELTA = '+1 to froggies'
_RESULT = '**Total froggies: {count}**'
_URL_CAUGHT = 'https://i.imgur.com/uwPIHMv.png'

# Failure
_FAIL = 'You were too slow!'


class Frogs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._frogs_spawner = list()


    class Spawner():
        def __init__(self, channel: discord.TextChannel, base_rate: int, timer):
            self._channel = channel
            self._base_rate = base_rate
            self._timer = timer

        def start(self):
            self._timer.start(self)

        def change_interval(self, **kwargs):
            self._timer.change_interval(**kwargs)

        def change_interval_random(self):
            self._timer.change_interval(minutes=self.random_spawn_time())

        def random_spawn_time(self):
            new = _SPAWNRATE_SWING*self._base_rate*uniform(-1, 1) + self._base_rate
            print('>> changing to {:.2f} minutes'.format(new))
            return new

        def get_channel(self):
            return self._channel


    @commands.group()
    async def frogs(self, ctx):
        pass


    @frogs.command()
    @commands.is_owner()
    async def fspawn(self, ctx):
        # Force a frog to spawn
        await self.spawn(ctx.channel)


    @frogs.command()
    async def start(self, ctx):
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        frogs_settings = guild_conf['frogs']

        if len(frogs_settings['channel_rates']) <= 0:
            await ctx.send('You have not registerd any channels to spawn frogs!')
            return

        frogs_settings['op'] = True

        channel_rates = list((ctx.guild.get_channel(cr[0]), cr[1]) for cr in frogs_settings['channel_rates'])

        # print(channels)
        # print([rate for rate in map(lambda r: r[1], channel_rates)])

        for i in range(len(channel_rates)):
            spawner = self.Spawner(channel_rates[i][0], channel_rates[i][1], copy(self.frog_timer))
            asyncio.create_task(self.delayed_start(spawner, minutes=spawner.random_spawn_time()))
            self._frogs_spawner.append(spawner)        

        # Message
        embed = make_simple_embed('Frogs will now start spawning in the following channels...', '\n'.join(ch[0].mention for ch in channel_rates))    
        embed.set_thumbnail(url='https://i.imgur.com/IR5htIF.png')
        await ctx.send(embed=embed)

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)


    @tasks.loop(minutes=_SPAWNRATE_DEFAULT)
    async def frog_timer(self, spawner):
        await self.spawn(spawner.get_channel())
        spawner.change_interval_random()


    async def delayed_start(self, spawner, seconds=0, minutes=0):
        await asyncio.sleep(seconds + 60 * minutes)
        spawner.change_interval_random()
        spawner.start()

    
    @frogs.command()
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


    async def spawn(self, channel):
        print('>> Spawning frog in channel {ch}...'.format(ch=channel))
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
                        description=_DELTA + '\n\n' + _RESULT.format(count=catcher_data['frogs']),
                        color=0x9edbf7)
            
            embed.set_thumbnail(url=_URL_CAUGHT)
            embed.set_footer(text='-sarono', icon_url='https://i.imgur.com/BAj8IWu.png')
            

            await msg_spawn.delete()
            await channel.send(content=catcher.mention, embed=embed)

            db_user_interface.write(self.bot.db_user, catcher.id, catcher_data)
        
        except asyncio.TimeoutError:
            await msg_spawn.delete()
            # await channel.send(_FAIL)


def setup(bot):
    bot.add_cog(Frogs(bot))