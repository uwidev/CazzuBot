import re

import emoji
import discord
from discord.ext import commands, tasks
import asyncio

PARSE_CLASS_VAR = re.compile(r'^(_[^_].*_)$')

class EmbedSummary:
    def __init__(self, title=None, description=None, thumbnail=None, color=None):
        self.title = title

        self.description = list()
        if description is None:
            pass
        elif type(description) is list:
            self.description.extend(description)
        elif type(description) is str:
            self.description.append(description)
        else:
            raise TypeError(f'EmbedSummary expected list, str, or None for paramater description, got {type(description)}')

        self.thumbnail = thumbnail
        self.color = color
        
        if any(map(lambda x: x not in [None, list()], self.__dict__.values())):
            self.touched = True
        else:
            self.touched = False

    @classmethod
    def from_summary(cls, other):
        obj = cls()
        obj.merge_left(other)
        return obj

    def merge_left(self, other):
        # Merges the embed passed to this embed. Anything not None on
        # other embed will override values on this embed.
        for k, v in other.__dict__.items():
            # if k == 'payload':
            #     # Payload updated like this to ensure correct ordering when unpacked
            #     other.payload.update(self.payload)
            #     self.payload = other.payload
            if k == 'description':
                self.description.extend(other.description)
            elif k == 'touched':
                self.touched = self.touched or other.touched
            elif v is not None:
                self.__dict__[k] = v
            


@tasks.loop(count=1)
async def timer(seconds: int, func=None, *args, **kwargs):
    # Function is working but is not working as intended. Prone to bugs.
    # 
    #
    # A timer that must be copy() in order to function independently
    # Begin timer with .start() or .restart() if already started
    #
    # @seconds: how long until calling {func}
    # @func: the function called after {seconds} seconds
    await asyncio.sleep(seconds)
    if not func:
        return
    
    if asyncio.iscoroutinefunction(func):
        await func(*args, **kwargs)
    else:
        func(*args, **kwargs)


class Timer():
    def __init__(self, callback, seconds=0, minutes=0, hours=0):
        self._callback = callback
        self._duration = seconds + 60*minutes + 3600*hours
        self._task = None
        self.is_running = False

    def start(self, *args, **kwargs):
        if self.is_running:
            raise RuntimeError('Timer is already running and is not yet complete!')

        self._task = asyncio.create_task(self._start(*args, **kwargs))
        self.is_running = True

        return self._task

    async def _start(self, *args, **kwargs):
        await asyncio.sleep(self._duration)
        self.is_running = False

        if asyncio.iscoroutinefunction(self._callback):
            await self._callback(*args, **kwargs)
        else:
            self._callback(*args, **kwargs)

    def restart(self, *args, **kwargs):
        '''
        Because of the nature of task scheduling, do not restart the timer and immediately cancel it. This method merely
        schedules for a restart when it is safe to do so. Meaning in order for it to actually be scheduled, we need to
        regularly do context switches until it is scheduled. Typically this is done naturally with await's, but if not 
        enough prevelant or you want to ensure that the timer has already been restarted, try the following:

            await asyncio.tasks.wait([task], return_when=asyncio.ALL_COMPLETED)

        Where [task] is the task(s) you want to ensure have restarted. task is returned from start(). The code resumes
        operation when the task is either cancelled or finishes.

        restart() does not return the _task.
        '''

        def restart_when_cancelled(future, args=args, kwargs=kwargs):
            self._task.remove_done_callback(restart_when_cancelled)
            self.start(*args, **kwargs)

        self._task.add_done_callback(restart_when_cancelled)
        self.cancel()
        
    def cancel(self):
        self.is_running = False
        self._task.cancel()

    def set_duration(self, seconds=0, minutes=0, hours=0):
        self._duration = seconds + 60*minutes + 3600*hours

    def get_currently_running_task(self):
        return self._task

    def __del__(self):
        self.cancel()


class ReadOnlyDict(dict):
    # This class is meant to only allow a read-only dictionary. 
    # It does not prevent mutable values from being changed.
    #
    # This is to ensure that the factory default settings of a guild never gets changed.
    def __setitem__(self, key, value):
        raise TypeError('read-only dictionary, setting values is not supported')

    def __delitem__(self, key):
        raise TypeError('read-only dict, deleting values is not supported')
    

async def is_custom_emoji(argument):
    '''Small helper function to see if an emoji is custom or unicode'''
    if argument in emoji.UNICODE_EMOJI or argument in emoji.UNICODE_EMOJI_ALIAS:
        return False
    return True


def emoji_regional_update():
    '''Adds regional letters to emoji for discord-compatability checking'''
    regional_emoji = {
        u'\U0001F1E6': u':regional_indicator_a:',
        u'\U0001F1E7': u':regional_indicator_b:',
        u'\U0001F1E8': u':regional_indicator_c:',
        u'\U0001F1E9': u':regional_indicator_d:',
        u'\U0001F1EA': u':regional_indicator_e:',
        u'\U0001F1EB': u':regional_indicator_f:',
        u'\U0001F1EC': u':regional_indicator_g:',
        u'\U0001F1ED': u':regional_indicator_h:',
        u'\U0001F1EE': u':regional_indicator_i:',
        u'\U0001F1EF': u':regional_indicator_j:',
        u'\U0001F1F0': u':regional_indicator_k:',
        u'\U0001F1F1': u':regional_indicator_l:',
        u'\U0001F1F2': u':regional_indicator_m:',
        u'\U0001F1F3': u':regional_indicator_n:',
        u'\U0001F1F4': u':regional_indicator_p:',
        u'\U0001F1F5': u':regional_indicator_o:',
        u'\U0001F1F6': u':regional_indicator_r:',
        u'\U0001F1F7': u':regional_indicator_s:',
        u'\U0001F1F8': u':regional_indicator_t:',
        u'\U0001F1F9': u':regional_indicator_q:',
        u'\U0001F1FA': u':regional_indicator_u:',
        u'\U0001F1FB': u':regional_indicator_v:',
        u'\U0001F1FC': u':regional_indicator_w:',
        u'\U0001F1FD': u':regional_indicator_x:',
        u'\U0001F1FE': u':regional_indicator_y:',
        u'\U0001F1FF': u':regional_indicator_z:'
        }

    emoji.UNICODE_EMOJI.update(regional_emoji)

class EmojiPlus(commands.EmojiConverter):
    async def convert(self, ctx, argument):
        if await is_custom_emoji(argument):
            return await super().convert(ctx, argument)
        return argument


# def is_emojiplus(bot, argument):
#     if type(argument) is int:
#         return True
#     return emoji.emoji_count(argument) >= 1 or bool(bot.get_emoji(argument))


# Consider doing proper ducktyping and making these embeds as classes that have a send function.
def make_simple_embed_t(title: str, desc: str):
    '''Creates a simple discord.embed object and returns it'''
    embed = discord.Embed(
                        title=title,
                        description=desc,
                        color=0x9edbf7)

    embed.set_footer(text='-sarono', icon_url='https://i.imgur.com/BAj8IWu.png')

    return embed


def make_simple_embed(desc: str, title: str):
    '''Creates a simple discord.embed object and returns it'''
    embed = discord.Embed(
                        title=title,
                        description=desc,
                        color=0x9edbf7)

    embed.set_footer(text='-sarono', icon_url='https://i.imgur.com/BAj8IWu.png')

    return embed


def make_error_embed(desc: str, title: str = 'ERROR'):
    '''Creates a simple error object and returns it'''
    embed = discord.Embed(
                        title=title,
                        description=desc,
                        color=0xff0000)

    embed.set_footer(text='-sarono', icon_url='https://i.imgur.com/BBwM9lr.png')

    return embed


def make_success_embed(desc: str, title: str = 'SUCCESS'):
    '''Creates a simple success object and returns it'''
    embed = discord.Embed(
                        title=title,
                        description=desc,
                        color=0x14a011) #14a011

    embed.set_footer(text='-sarono', icon_url='https://i.imgur.com/rE4YR6C.png')

    return embed


templates_embed = {
    'simple':make_simple_embed,
    'success':make_success_embed,
    'error':make_error_embed
}


async def quick_embed(ctx, type: str, desc: str, title: str = None):
    '''
    Quickly send an embedded messages from defined templates.
    '''
    if title is None:
        await ctx.send(embed=templates_embed[type](desc))
    else:
        await ctx.send(embed=templates_embed[type](desc, title))


async def request_user_confirmation(ctx, bot, desc: str, title: str = 'Confirmation', delete_after: bool = True) -> bool:
    request_from = ctx.author
    
    if title is None:
        embed = make_simple_embed(desc, 'CONFIRMATION')
    else:  
        embed = make_simple_embed(desc, title)
    embed.color = 0xfffa4d
    
    confirmation = await ctx.send(embed=embed)
    await confirmation.add_reaction('❌')
    await confirmation.add_reaction('✅')
    
    def check(reaction, user):
                if user.id == request_from.id and reaction.message.id == confirmation.id:
                    if reaction.emoji in ['❌', '✅']:
                        return True
            
                return False
    
    try:
        reaction, consumer = await bot.wait_for('reaction_add', check=check, timeout=10)
    except asyncio.TimeoutError:
        if delete_after:
            await confirmation.delete()
        return False
    
    if reaction.emoji == '❌':
        if delete_after:
            await confirmation.delete()
        return False

    if delete_after:
        await confirmation.delete()

    return True


def writiable_emoji(emo):
    return emo if type(emo) is discord.emoji.Emoji else emo


def is_admin():
    ''' Decorator for a specific command to check for admin perms. '''
    def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    
    return commands.check(predicate)