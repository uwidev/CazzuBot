import re

import emoji
import discord
from discord.ext import commands, tasks
import asyncio

PARSE_CLASS_VAR = re.compile(r'^(_[^_].*_)$')

@tasks.loop(count=1)
async def timer(seconds: int, func=None, *args, **kwargs):
    # Function is working but is not working as intended. Prone to bugs.
    # 
    #
    # A timer that must be copy() in order to function independently
    # Begin timer with .start() or .restart() if alreaady started
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


def make_simple_embed(title: str, desc: str):
    '''Creates a simple discord.embed object and returns it'''
    embed = discord.Embed(
                        title=title,
                        description=desc,
                        color=0x9edbf7)

    embed.set_footer(text='-sarono', icon_url='https://i.imgur.com/BAj8IWu.png')

    return embed


def writiable_emoji(emo):
    return emo if type(emo) is discord.emoji.Emoji else emo