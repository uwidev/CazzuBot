# This cog holds all the commands and their functionality that can only be ran by the bot owner.

import asyncio, os, re
from collections import defaultdict

import discord
from discord.ext import commands
from tinydb import Query
import db_guild_interface, db_user_interface
import emoji
from utility import EmojiPlus, writiable_emoji, make_simple_embed

import customs.cog

class Owner(customs.cog.Cog):
    '''
    These are commands meant to be ran only by the owner.
    '''
    async def cog_after_invoke(self, ctx):
        # await ctx.message.add_reaction('👍')
        # await ctx.message.delete(delay=3)
        pass


    async def cog_check(self, ctx):
        # Called whhhenever someone tries to invoke a command in this cog
        #
        # @return: bool. If true then the command will run, else command will fail
        if await self.bot.is_owner(ctx.author):
            return True
        return False


    @commands.group()
    async def compile(self, ctx):
        pass


    @compile.command(name = 'emojis')
    async def emojis(self, ctx):
        # Saves all emojis of this guild onto storage
        emojis = ctx.guild.emojis

        for emoji in emojis:
            print("Saving emoji to... " + os.getcwd() + '\\' + emoji.name + str(emoji.url)[-4:])
            await emoji.url.save(os.getcwd() + '\\' + emoji.name + str(emoji.url)[-4:])
        
        await ctx.send('Emojis have been saved in storage.')


    @commands.group()
    async def verify(self, ctx):
        pass


    @verify.command(name = 'make')
    async def verify_make(self, ctx, msg:discord.Message, emo:EmojiPlus, *, rol:discord.Role):
        '''
        Reacts to a message (given messsage id) withh the provided emoji. Anyone afterwards who reacts with
        that emoji will be given the provided role.
        '''
        # Creates the embed for the verify module.
        #
        # @msg: The id of the message to watch reactions for verification
        # @emo: The reaction to look for to apply the {rol}
        # @rol: The role to give the member
        if ctx.guild.me.top_role <= rol:
            await ctx.send('It appears that role is higher than what I could ever get :c')
            return
        
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        verify_settings = guild_conf['verify']
        
        
        verify_settings['channel'] = ctx.channel.id
        verify_settings['message'] = msg.id
        verify_settings['emoji'] = writiable_emoji(str(emo))
        verify_settings['role'] = rol.id
        verify_settings['op'] = True
        await msg.add_reaction(emo)

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)


    @verify.command(name = 'emoji')
    async def verify_emoji(self, ctx, emo:EmojiPlus):
        '''
        Edits an existing verify message (if exists) such that it's new watched reaction is {emo}.
        '''
        # @emo: the new reaction to watch to apply role verification
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        verify_settings = guild_conf['verify']

        
        channel_id = verify_settings['channel']
        msg_id = verify_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        
        await msg.remove_reaction(verify_settings['emoji'], ctx.guild.me)
        await msg.add_reaction(str(emo))

        verify_settings['emoji'] = str(emo)
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)
    

    @verify.command(name = 'role')
    async def verify_role(self, ctx, *, rol:discord.Role):
        '''
        Edits and existing verify message (if existss) such that the new role it gives to members is {rol}.
        '''
        # @rol: the new role to give
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        verify_settings = guild_conf['verify']

        verify_settings['role'] = rol.id

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)


    @commands.group()
    async def welcome(self, ctx):
        pass


    @welcome.command(name = 'here')
    async def welcome_here(self, ctx):
        '''
        Sets this current ctx.channel as the channel to welcome new users.
        '''
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        welcome_settings = guild_conf['welcome']

        welcome_settings['op'] = True
        welcome_settings['channel'] = ctx.channel.id

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)
        await ctx.message.add_reaction('👍')


    @welcome.command(name = 'content')
    async def welcome_content(self, ctx, *, content: str):
        '''
        Edits the message that gets sent when a new user joins.
        '''
    # @ content: the message of the new embed
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        welcome_settings = guild_conf['welcome']

        welcome_settings['content'] = content

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)
        await ctx.message.add_reaction('👍')


    @welcome.command(name = 'title')
    async def welcome_title(self, ctx, *, title: str):
        '''
        Edits the embedded title that gets sent when a new user joins
        '''
    # @ title: the new embed title
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        welcome_settings = guild_conf['welcome']

        welcome_settings['title'] = title

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)
        await ctx.message.add_reaction('👍')
        # await ctx.message.delete(delay=2)


    @welcome.command(name = 'description', aliases=['desc'])
    async def welcome_desc(self, ctx, *, desc: str):
        '''
        Edits the embedded description that gets sent when a new user joins.
        '''
        #
        # @ desc: the new embed description
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        welcome_settings = guild_conf['welcome']

        welcome_settings['description'] = desc

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)
        await ctx.message.add_reaction('👍')
        # await ctx.message.delete(delay=2)


    @commands.command()
    async def listemojis(self, ctx):
        '''
        Lists all emojis the server has to offer with their name.
        '''
        async with ctx.channel.typing:
            for emoji in ctx.guild.emojis():
                await ctx.send(emoji)
                await ctx.send('**`:' + emoji.name + ':`**')
                await asyncio.sleep(1)
        
        await ctx.message.delete()
    

    @commands.command()
    async def init_hard(self, ctx):
        '''
        Completely wipes guild's settings.
        '''
        self.bot.db_guild.truncate()
        await ctx.send("Done!")


    @commands.group()
    async def patch(self, ctx):
        pass


    @patch.command()
    async def guilds(self, ctx):
        '''
        Updates the database so outdated server settings are current.
        '''
        m1 = await ctx.send('Updating the db for all guilds I am connected to...')
        
        async with ctx.channel.typing():
            gids_generator = (g.id for g in self.bot.guilds)

            for gid in gids_generator:
                db_guild_interface.upgrade(self.bot.db_guild, gid)

        m2 = await ctx.send('Database is now updated!')

        await asyncio.sleep(2)
        for m in [m1, m2, ctx.message]:
            await m.delete()
    

    @patch.command()
    async def users(self, ctx):
        m1 = await ctx.send('Updating all users to the latest default user structure...')
        db_user_interface.upgrade(self.bot.db_user)
        m2 = await ctx.send('Database is now updated!')

        await asyncio.sleep(2)
        for m in [m1, m2, ctx.message]:
            await m.delete()


    @commands.group()
    async def counter(self, ctx):
        pass
    

    @counter.command(name = 'make')
    async def counter_make(self, ctx):
        '''
        Creates a counter module for the guild in this channel.
        '''
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
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
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)
        

    @counter.command(name = 'emoji')
    async def counter_emoji(self, ctx, emo: EmojiPlus):
        '''
        Sets the emoji for the counter module.
        '''
        # @emo: the new emoji to look for
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        
        await msg.remove_reaction(counter_settings['emoji'], ctx.guild.me)
        await msg.add_reaction(emo)
        
        counter_settings['emoji'] = str(emo)
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)


    @counter.command(name = 'title')
    async def counter_title(self, ctx, title: str):
        '''
        Edits the embedded title for the counter module.
        '''
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        embed = msg.embeds[0]
        
        embed.title = title
        await msg.edit(embed=embed)

        counter_settings['title'] = title
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)


    @counter.command(name = 'description')
    async def counter_desc(self, ctx, desc: str):
        '''
        Edits the embedded description for the counter module.
        '''       
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        embed = msg.embeds[0]
        
        embed.description = desc
        await msg.edit(embed=embed)

        counter_settings['description'] = desc
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)


    @counter.command(name = 'footer')
    async def counter_footer(self, ctx, footer: str):
        '''
        Edits the embedded footer for the counter module.
        '''
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        embed = msg.embeds[0]
        
        embed.set_footer(text=footer)
        await msg.edit(embed=embed)

        counter_settings['footer'] = footer
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)


    @counter.command(name = 'thumbnail')
    async def counter_thumbnail(self, ctx, url: str):
        '''
        Edits the embedded thumbnail for the counter module.
        '''
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        embed = msg.embeds[0]
        
        embed.set_thumbnail(url=url)
        await msg.edit(embed=embed)

        counter_settings['thumbnail'] = url
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)


    @counter.command(name = 'set')
    async def counter_set(self, ctx, count: int):
        '''
        Edits the current count for the counter module.
        '''        
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        counter_settings = guild_conf['counter']

        channel_id = counter_settings['channel']
        msg_id = counter_settings['message']
        msg = await ctx.guild.get_channel(channel_id).fetch_message(msg_id)
        embed = msg.embeds[0]
        
        embed.description = counter_settings['description'].format(count=count)
        await msg.edit(embed=embed)

        counter_settings['count'] = count
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, guild_conf)


    @commands.group()
    async def story(self, ctx):
        pass


    @story.command(name='compile')
    async def story_compile(self, ctx):
        '''
        Saves all message in a .txt file as one long message. Also summarizes the contributions.
        File name will be the same as the channel name.
        '''
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
            await ctx.message.delete()


    @story.command()
    async def write(self, ctx, file_name):
        '''
        Given a existing file name from a compiled story, writes the entire story.
        '''
        await ctx.send("```fix\n>>> {name} <<<```".format(name=file_name))
        async with ctx.channel.typing():
            with open('story/{ch}.txt'.format(ch=file_name), mode='r', encoding='utf-8') as file:
                while True:
                    i = 0
                    to_append = ''
                    to_print = ''
                    eof_reached = 0

                    while(i <= 1900 or to_append != ' '):
                        to_append = file.read(1)
                        
                        if not to_append:
                            # print('>>> reached EOF')
                            eof_reached = 1
                            break
                        
                        to_print += to_append
                        i += 1
                        
                    await ctx.send(to_print)
                    await asyncio.sleep(2)
                    if eof_reached == 1:
                        break
            
            with open('story/{ch}-contibutors.txt'.format(ch=file_name), mode='r', encoding='utf-8') as file:
                while True:
                    i = 0
                    to_append = ''
                    to_print = ''
                    eof_reached = 0

                    while(i <= 1900 or to_append != ' '):
                        to_append = file.read(1)
                        
                        if not to_append:
                            # print('>>> reached EOF')
                            eof_reached = 1
                            break
                        
                        to_print += to_append
                        i += 1
                        
                    # print('going to print {}'.format(to_print))
                    await ctx.send(to_print)
                    if eof_reached == 1:
                        break
                    await asyncio.sleep(2)

        await ctx.message.delete()


    @commands.command()
    async def reload(self, ctx, *, ext_name):
        ext = 'cog.' + ext_name
        if ext not in self.bot.extensions:
            await ctx.send(embed=make_simple_embed('ERROR', 'Extension doesn\'t exist or you can\'t spell!'))
            raise commands.BadArgument
        
        try:
            self.bot.reload_extension(ext)
            await ctx.send(embed=make_simple_embed('Success', f'{ext_name.capitalize()} has been reloaded'))
        except Exception as e:
            await ctx.send(embed=make_simple_embed('ERROR', 'There appears to be a problem with your code, baka.'))
            raise e

    @commands.command()
    async def load(self, ctx, ext_name):
        ext = ext_name + '.py'
        dir = os.listdir('cog')
        
        if ext in dir:
            try:
                self.bot.load_extension('cog.' + ext_name)
                await ctx.send(embed=make_simple_embed('Success', f'{ext_name.capitalize()} has been loaded'))
            except Exception as e:
                await ctx.send(embed=make_simple_embed('ERROR', 'Something terrible happened!'))
                raise e
        else:
            await ctx.send(embed=make_simple_embed('ERROR', 'File doesn\'t exist or you can\'t spell!'))

    @commands.command()
    async def unload(self, ctx, ext_name):
        ext = 'cog.' + ext_name
        if ext not in self.bot.extensions:
            await ctx.send(embed=make_simple_embed('ERROR', 'Extension wasn\'t loaded to begin with!'))
            raise commands.BadArgument
        
        
        dir = os.listdir('cog')
        if ext_name + '.py' in dir:
            try:
                self.bot.unload_extension('cog.' + ext_name)
                await ctx.send(embed=make_simple_embed('Success', f'{ext_name.capitalize()} has been unloaded'))
            except Exception as e:
                await ctx.send(embed=make_simple_embed('ERROR', 'Something terrible happened!'))
                raise e
        else:
            await ctx.send(embed=make_simple_embed('ERROR', 'Extension doesn\'t exist or you can\'t spell!'))


def setup(bot):
    bot.add_cog(Owner(bot))