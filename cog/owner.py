import asyncio, os, re
from collections import defaultdict

import discord
from discord.ext import commands
from tinydb import Query
from interfacedb import *
import emoji
from utility import EmojiPlus, writiable_emoji

class Owner(commands.Cog):
    # These commands are only executable by the owner of the bot
    def __init__(self, bot):
        self.bot = bot

    # async def cog_command_error(self, ctx, error):
    #     if error is commands.CheckFailure:
    #         pass
    #     raise error


    async def cog_after_invoke(self, ctx):
        await ctx.message.add_reaction('👍')
        # await ctx.message.delete(delay=3)


    async def cog_check(self, ctx):
        # Check to ensure the user running these commands is the owner of this bot
        if await self.bot.is_owner(ctx.author):
            return True
        return False


    @commands.command()
    async def ping(self, ctx):
        await ctx.send(':ping_pong: Pong! {}ms'.format(str(self.bot.latency * 1000)[0:6]))


    @commands.group()
    async def fetch(self, ctx):
        pass


    @fetch.command(name = 'emojis')
    async def save_all_emojis(self, ctx):
        emojis = ctx.guild.emojis

        for emoji in emojis:
            print("Saving emoji to... " + os.getcwd() + '\\' + emoji.name + str(emoji.url)[-4:])
            await emoji.url.save(os.getcwd() + '\\' + emoji.name + str(emoji.url)[-4:])


    @commands.group()
    async def verify(self, ctx):
        pass


    @verify.command(name = 'make')
    async def verify_make(self, ctx, msg:discord.Message, emo:EmojiPlus, *, rol:discord.Role):
        if ctx.guild.me.top_role <= rol:
            await ctx.send('It appears that role is higher than what I could ever get :c')
            return
        
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        verify_settings = guild_conf['verify']
        
        
        verify_settings['channel'] = ctx.channel.id
        verify_settings['message'] = msg.id
        verify_settings['emoji'] = writiable_emoji(str(emo))
        verify_settings['role'] = rol.id
        verify_settings['op'] = True
        await msg.add_reaction(emo)

        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)
        
        # await ctx.message.add_reaction('👍')
        # await ctx.message.delete(delay=2)


    @verify.command(name = 'emoji')
    async def verify_emoji(self, ctx, emo:EmojiPlus):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        verify_settings = guild_conf['verify']

        
        channel_id = verify_settings['channel']
        msg_id = verify_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        
        await msg.remove_reaction(verify_settings['emoji'], ctx.guild.me)
        await msg.add_reaction(str(emo))

        verify_settings['emoji'] = str(emo)
        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)
        
        # await ctx.message.add_reaction('👍')
        # await ctx.message.delete(delay=2)

    
    @verify.command(name = 'role')
    async def verify_role(self, ctx, *, rol:discord.Role):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        verify_settings = guild_conf['verify']

        verify_settings['role'] = rol.id

        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)
        
        # await ctx.message.add_reaction('👍')
        # await ctx.message.delete(delay=2)


    @commands.group()
    async def welcome(self, ctx):
        pass


    @welcome.command(name = 'here')
    async def welcome_here(self, ctx):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        welcome_settings = guild_conf['welcome']

        welcome_settings['op'] = True
        welcome_settings['channel'] = ctx.channel.id

        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)
        await ctx.message.add_reaction('👍')


    @welcome.command(name = 'content')
    async def welcome_content(self, ctx, *, content):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        welcome_settings = guild_conf['welcome']

        welcome_settings['content'] = content

        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)
        await ctx.message.add_reaction('👍')


    @welcome.command(name = 'title')
    async def welcome_title(self, ctx, *, title):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        welcome_settings = guild_conf['welcome']

        welcome_settings['title'] = title

        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)
        # await ctx.message.add_reaction('👍')
        # await ctx.message.delete(delay=2)


    @welcome.command(name = 'description')
    async def welcome_desc(self, ctx, *, desc):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        welcome_settings = guild_conf['welcome']

        welcome_settings['description'] = desc

        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)
        # await ctx.message.add_reaction('👍')
        # await ctx.message.delete(delay=2)


    @commands.command()
    async def listemojis(self, ctx):
        async with ctx.channel.typing:
            for emoji in ctx.guild.emojis():
                await ctx.send(emoji)
                await ctx.send('**`:' + emoji.name + ':`**')
                await asyncio.sleep(1)
        
        await ctx.message.delete()
    

    @commands.command()
    async def init_hard(self, ctx):
        self.bot.db_confs.truncate()
        await ctx.send("Done!")


    @commands.command()
    async def update_guild_dbs(self, ctx):
        m1 = await ctx.send('Updating the db for all guilds I am connected to...')
        
        async with ctx.channel.typing():
            gids_generator = (g.id for g in self.bot.guilds)

            for gid in gids_generator:
                update_settings(self.bot.db_confs, gid)

        m2 = await ctx.send('Database is now updated!')

        await asyncio.sleep(2)
        for m in [m1, m2, ctx.message]:
            await m.delete()


    @commands.group()
    async def counter(self, ctx):
        pass
    

    @counter.command(name = 'make')
    async def counter_make(self, ctx):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        counter_settings = guild_conf['counter']

        title = counter_settings['title']
        desc = counter_settings['description']
        count = counter_settings['count']
        foot = counter_settings['footer']
        thum = counter_settings['thumbnail']

        embed = discord.Embed(
                        title=title,
                        description=desc.format(count=count),
                        color=0x9edbf7)
        
        embed.set_thumbnail(url=thum)
        embed.set_footer(text=foot, icon_url='https://cdn.discordapp.com/emojis/695126166301835304.png?v=1')

        msg = await ctx.send(embed=embed)

        counter_settings['message'] = msg.id
        counter_settings['channel'] = ctx.channel.id
        counter_settings['op'] = True

        await msg.add_reaction(counter_settings['emoji'])
        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)
        

    @counter.command(name = 'emoji')
    async def counter_emoji(self, ctx, emo: EmojiPlus):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        
        await msg.remove_reaction(counter_settings['emoji'], ctx.guild.me)
        await msg.add_reaction(emo)
        
        counter_settings['emoji'] = str(emo)
        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)


    @counter.command(name = 'title')
    async def counter_title(self, ctx, title: str):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        embed = msg.embeds[0]
        
        embed.title = title
        await msg.edit(embed=embed)

        counter_settings['title'] = title
        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)


    @counter.command(name = 'description')
    async def counter_desc(self, ctx, desc: str):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        embed = msg.embeds[0]
        
        embed.description = desc
        await msg.edit(embed=embed)

        counter_settings['description'] = desc
        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)


    @counter.command(name = 'footer')
    async def counter_footer(self, ctx, footer: str):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        embed = msg.embeds[0]
        
        embed.set_footer(text=footer)
        await msg.edit(embed=embed)

        counter_settings['footer'] = footer
        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)


    @counter.command(name = 'thumbnail')
    async def counter_thumbnail(self, ctx, url: str):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        embed = msg.embeds[0]
        
        embed.set_thumbnail(url=url)
        await msg.edit(embed=embed)

        counter_settings['thumbnail'] = url
        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)


    @counter.command(name = 'set')
    async def counter_set(self, ctx, count: int):
        guild_conf = get_guild_conf(self.bot.db_confs, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        embed = msg.embeds[0]
        
        embed.description = counter_settings['description'].format(count=count)
        await msg.edit(embed=embed)

        counter_settings['count'] = count
        write_back_settings(self.bot.db_confs, ctx.guild.id, guild_conf)


    @commands.command()
    async def story(self, ctx):
        channel = ctx.channel
        contributions = 0
        emoji = re.compile(r'(<a?:[a-zA-Z0-9\_]+:[0-9]+>)')
        contributors = defaultdict(int)

        async with channel.typing():
            if not os.path.isdir('story'):
                    os.makedirs('story')

            participants = defaultdict(int)
            with open('story/{ch}.txt'.format(ch=channel.name), mode='w', encoding='utf-8') as file:
                async for message in channel.history(limit=None, before=ctx.message, oldest_first=True):
                    contributors[message.author.name] += 1

                    file.write('{m} '.format(m=message.content))
                    contributions += 1
                    participants[message.author] += 1
                

                with open('story/{ch}-contibutors.txt'.format(ch=channel.name), mode='w', encoding='utf-8') as file:               
                    file.write('.\n.\n.\n__**Total contributions: {c}**__\n'.format(c=contributions))

                    i = 0
                    for item in sorted(contributors.items(), key=lambda x: x[1], reverse=True):
                        percent = (item[1]/contributions)
                        if i < 5:
                            file.write('**{auth}: {times} ({perc:.2%})**\n'.format(auth=item[0], times=item[1], perc=percent))
                        else:
                            file.write('{auth}: {times} ({perc:.2%})\n'.format(auth=item[0], times=item[1], perc=percent))
                        i += 1

            
            # msg = await channel.send('🎉 Done compiling 🎉')
            # await msg.delete(delay=3)
            # await ctx.message.delete()


def setup(bot):
    bot.add_cog(Owner(bot))