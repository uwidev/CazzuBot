import emoji
import discord
from discord.ext import commands, tasks
import asyncio

# class Timer:
#     def __init__(self, timeout, callback):
#         self._timeout = timeout
#         self._callback = callback
#         self._task = asyncio.ensure_future(self._job())
#         self.running = True

#     async def _job(self):
#         await asyncio.sleep(self._timeout)
#         self.running = False
#         await self._callback()

#     def cancel(self):
#         self._task.cancel()

#     async def restart(self):
#         self._task.cancel()
#         await self._job()


# def test():
#     pass

# s = MembersDecay(test)
# s[0]
# s[1]
# s[2]
# print(s)


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

# def get_group(guild_conf: dict, to_find: str):
#     for name in guild_conf['groups'].keys():
#         if name == to_find:
#             return guild_conf['groups'][name]
#     return None