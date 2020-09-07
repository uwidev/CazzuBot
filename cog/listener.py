# This cog is meant to listen to events in a guild and react
#
# DO NOT PUT COMMANDS HERE

import asyncio, os
from collections import defaultdict
from copy import copy

import discord, db_guild_interface
from discord.ext import commands, tasks
from tinydb import Query
from utility import make_simple_embed, timer

class Listener(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.counter_lock = False
        self.recently_counted = dict()


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
    # Called on any and all reactionss
    #
    # Is organaized in the following:
    #   User authentication
    #   Counter
        if payload.member.id == self.bot.user.id:
            return

        # Ensure dependencies of all reaction-related events
        await self.ensure_dependencies(payload.guild_id)
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, payload.guild_id)
        
        # Automation for User Verification
        verify_settings = guild_conf['verify']
        if verify_settings['op']:
            if self.verify_reaction(verify_settings, payload):             
                try:
                    await payload.member.add_roles(payload.member.guild.get_role(verify_settings['role']))
                    # Automation for welcoming new members
                    welcome_settings = guild_conf['welcome']
                    if welcome_settings['op']:
                        channel = self.bot.get_channel(welcome_settings['channel'])
                        embed = make_simple_embed(welcome_settings['title'], welcome_settings['description'])
                        await channel.send(welcome_settings['content'].format(user=payload.member.mention), embed=embed)
                
                except discord.Forbidden:
                    pass
        
        # Counter event checking
        #
        # Uses a lock to ensure that multiple calals aren't ran multiple times
        # when multiple users add rections to the counter
        if not self.counter_lock:
            counter_settings = guild_conf['counter']
            if counter_settings['op']:
                if self.verify_reaction(counter_settings, payload):
                    self.counter_lock = True
                    await asyncio.sleep(3)
                    msg = await payload.member.guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
                    
                    for reaction in msg.reactions:
                        if str(reaction) == counter_settings['emoji']:
                            async for member in reaction.users():
                                if member == payload.member.guild.me:
                                    continue
                                counter_settings['count'] += 1

                                # Start decaying for recently counted, note that the actual recent timer will be sleep + the first argument
                                if member not in self.recently_counted:
                                    self.recently_counted[member] = copy(timer)
                                    self.recently_counted[member].start(297, self.counter_member_decay, member)
                                else:
                                    self.recently_counted[member].restart(297, self.counter_member_decay, member)
                                
                            # Fetch counter embed from message and modify it
                            embed = msg.embeds[0]
                            embed.description = counter_settings['description'].format(count=counter_settings['count'])
                            members = list(self.recently_counted.keys())
                            
                            # String creation for recently counted footer
                            count = len(members)
                            if count > 0:
                                if count > 2:     
                                    mentions = ', '.join(member.name for member in members[:-1]) + f', and {members[-1].name}'
                                elif count == 2:
                                    mentions = ' and '.join(member.name for member in members)
                                elif count == 1:
                                    mentions = members[0].name
                                embed.set_footer(text='{mentions} recently did a baka!'.format(mentions=mentions), icon_url='https://cdn.discordapp.com/emojis/695126168164237363.png?v=1')
                            else:
                                embed.set_footer(text=counter_settings['footer'], icon_url='https://cdn.discordapp.com/emojis/695126166301835304.png?v=1')   

                            # Finalize and modify the message
                            await msg.edit(embed=embed)
                            await msg.clear_reactions()
                            await msg.add_reaction(counter_settings['emoji'])

                            touch = await msg.channel.send('.')
                            await touch.delete()

                            # Write back to DB the changed counter
                            db_guild_interface.write(self.bot.db_guild, payload.guild_id, guild_conf)
                    
                    self.counter_lock = False


    async def counter_member_decay(self, member):
        # Called after {seconds} from counter
        #
        # @member: the member we want to remove from recently counted
        if member not in self.recently_counted:
            print('Warning: for some reason, {m} wasn\'t found in recently counted for counter module.'.format(m=member.name))
            return

        self.recently_counted.pop(member)
        await self.ensure_dependencies(member.guild.id)
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, member.guild.id)
        counter_settings = guild_conf['counter']

        msg = await member.guild.get_channel(counter_settings['channel']).fetch_message(counter_settings['message'])

        # Fetch embed from message and modify it
        embed = msg.embeds[0]
        embed.description = counter_settings['description'].format(count=counter_settings['count'])
        members = list(self.recently_counted.keys())
        
        # String creation for recently counted footer
        count = len(members)
        if count > 0:
            if count > 2:     
                mentions = ', '.join(member.name for member in members[:-1]) + f', and {members[-1].name}'
            elif count == 2:
                mentions = ' and '.join(member.name for member in members)
            elif count == 1:
                mentions = members[0].name
            embed.set_footer(text='{mentions} recently did a baka!'.format(mentions=mentions), icon_url='https://cdn.discordapp.com/emojis/695126168164237363.png?v=1')
        else:
            embed.set_footer(text=counter_settings['footer'], icon_url='https://cdn.discordapp.com/emojis/695126166301835304.png?v=1')        
                            
        await msg.edit(embed=embed)
                    

    # @tasks.loop(count=1)
    # async def decay_recently_counted(self, seconds, payload):
    #     await asyncio.sleep(seconds)
    #     await self.ensure_dependencies(payload.guild_id)
    #     guild_conf = get_guild_conf(self.bot.db_guild, payload.guild_id)
    #     counter_settings = guild_conf['counter']

    #     if counter_settings['op']:
    #         if self.verify_reaction(counter_settings, payload):
    #             msg = await payload.member.guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
    #             embed = msg.embeds[0]
    #             embed.set_footer(text=counter_settings['footer'], icon_url='https://cdn.discordapp.com/emojis/695126166301835304.png?v=1')
                
    #             await msg.edit(embed=embed)


    def verify_reaction(self, settings, payload):
        # Checks to see if reaction is on the right message and the right emoji
        #
        # @settings: the group settings of a guild
        # @payload: the payload from a raw reaction
        #
        # @return: bool
        return (str(payload.emoji) == settings['emoji'] and 
            payload.channel_id == settings['channel'] and 
            payload.message_id == settings['message'])


    async def ensure_dependencies(self, gid):
    # Checks if data is still relevant to a guild, and if not set
    # the settings to inoperable to speed up computation
    #
    # @gid: guild id to check dependencies
        affected = False
        guild_conf = db_guild_interface.fetch(self.bot.db_guild, gid)

        for name, settings in guild_conf.items():
            # Check Verify dependencies here
            if name == 'verify':
                if settings['op'] == True:                    
                    # Ensure channel, emoji and role exists
                    emoji = settings['emoji'] if self.bot.get_emoji(settings['emoji']) != None else settings['emoji']

                    if (not emoji or not self.bot.get_guild(gid).get_role(settings['role']) or 
                        not self.bot.get_channel(settings['channel'])):
                        affected = True
                        settings['op'] = False
                        continue
                
                    # Ensure message exists
                    try:
                        await self.bot.get_channel(settings['channel']).fetch_message(settings['message'])
                    except discord.NotFound:
                        affected = True
                        settings['op'] = False
                        continue

        if affected:
            # self.bot.db_guild.update([guild_conf])
            pass


    @commands.command()
    async def test(self, ctx):
    # Looks at all messages in a channel and returns the rating of all messsages
    # based on 👍 and 👎, then sends a report into the channel
        info_pnts = dict()
        his = ctx.channel.history

        # Add all the messages into the info_pnts dictionary
        async for message in his():
            points = 0
            for reaction in message.reactions:
                if reaction.emoji == "👍":
                    points += reaction.count
                elif reaction.emoji == "👎":
                    points -= reaction.count
            info_pnts[message] = points
        
        info_pnts = {k: v for k, v in sorted(info_pnts.items(), key = lambda item: -item[1])}
        message, votes = next(iter(info_pnts.items()))
        await ctx.send("WINNERS:\nMessage with the most votes:\n{}\nAuthor: {}\nVotes: {}".format(message.content, message.author, votes))



    # @noot.error
    # async def info_error(self, ctx, error):
    #     if isinstance(error, commandsBadArgumnet):
    #         await ctx.send('STOP')


    # @commands.Cog.listener()
    # async def on_raw_message_delete(self, payload):
    #     # If a server module depended on a deleted message,
    #     # set that module to inoperable
    #     affected = False

    #     server_conf = self.bot.conf.get(Query().guild_id == payload.guild_id)
    #     for group in server_conf['groups']:
    #         if group['op']:
    #             settings = group['settings']
    #             if 'channel' in settings and 'message' in settings:
    #                 if payload.channel_id == settings['channel'] and payload.message_id == settings['message']:
    #                     group['op'] = False
    #                     affected = True
    #     if affected:
    #         self.bot.conf.update([server_conf])


    # @commands.Cog.listener()
    # async def on_raw_bulk_message_delete(self, payload):
    #     # If a server module depended on a deleted message,
    #     # set that module to inoperable
    #     affected = False

    #     server_conf = self.bot.conf.get(Query().guild_id == payload.guild_id)
    #     for group in server_conf['groups']:
    #         if group['op']:
    #             settings = group['settings']
    #             if 'channel' in settings and 'message' in settings:
    #                 if payload.channel_id == settings['channel'] and settings['message'] in payload.message_ids:
    #                     group['op'] = False
    #                     affected = True
        
    #     if affected:
    #         self.bot.conf.update([server_conf])


    # @commands.Cog.listener()
    # async def on_guild_channel_delete(self, channel):
    #     # If a server module depended on a deleted channel,
    #     # set that module to inoperable
    #     affected = False

    #     server_conf = self.bot.conf.get(Query().guild_id == channel.guild.id)
    #     for group in server_conf['groups']:
    #         if group['op']:
    #             settings = group['settings']
    #             if 'channel' in settings:
    #                 if channel.id == settings['channel']:
    #                     group['op'] = False
    #                     affected = True
        
    #     if affected:
    #         self.bot.conf.update([server_conf])


    # @commands.Cog.listener()
    # async def on_guild_role_delete(self, role):
    #     # If a server module depended on a deleted role,
    #     # set that module to inoperable
    #     affected = False

    #     server_conf = self.bot.conf.get(Query().guild_id == role.guild.id)
    #     for group in server_conf['groups']:
    #         if group['op']:
    #             settings = group['settings']
    #             if 'role' in settings:
    #                 if role.id == settings['role']:
    #                     group['op'] = False
    #                     affected = True
        
    #     if affected:
    #         self.bot.conf.update([server_conf])


    # @commands.Cog.listener()
    # async def on_guild_emojis_update(self, guild, before, after):
    #     # If a server module depended on a deleted emoji,
    #     # set that module to inoperable
    #     deleted = set(before) - set(after)
    #     affected = False

    #     server_conf = self.bot.conf.get(Query().guild_id == guild.id)
    #     for group in server_conf['groups']:
    #         if group['op']:
    #             settings = group['settings']
    #             if 'emoji' in settings:
    #                 if settings['emoji'] in deleted:
    #                     group['op'] = False
    #                     affected = True
        
    #     if affected:
    #         self.bot.conf.update([server_conf])


def setup(bot):
    bot.add_cog(Listener(bot))