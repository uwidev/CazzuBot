# Helper functions
import logging
import asyncio

import discord
from discord.ext import commands


_log = logging.getLogger('discord')
_log.setLevel(logging.INFO)


class ReadOnlyDict(dict):
    """Safeguard to prevent writing to DB templates."""
    def __setitem__(self, key, value):
        raise TypeError('read-only dictionary, '
                        'setting values is not supported')

    def __delitem__(self, key):
        raise TypeError('read-only dict, '
                        'deleting values is not supported')


def author_confirm(confirmation_msg: str = "Please confirm.",
                   delete_after: bool = True):
    """Decorator that makes a command require author confirmation."""
    async def confirm(ctx: commands.Context) -> bool:
        author = ctx.author
        confirmation = await ctx.send(confirmation_msg)
        await confirmation.add_reaction('❌')
        await confirmation.add_reaction('✅')

        def check(reaction, user):
            if user.id == author.id and reaction.message.id == confirmation.id:
                if reaction.emoji in ['❌', '✅']:
                    return True

            return False

        try:
            reaction, _ = await ctx.bot.wait_for('reaction_add',
                                            check=check,
                                            timeout=10)
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

    return commands.check(confirm)


def update_dict(old: dict, ref: dict, new: dict = {}) -> dict:
    """Returns a new dictionary that matches the reference, retaining values.
    
    Example
        Input
        old = {'a': 3, 'b': {'x': 5}, 'c': 7}
        ref = {'a': 0, 'b': {'y': 0}, 'd': 2}
        new = {}

        Returns
        {'a': 3, 'b': {'y': 0}, 'd': 2}
    """
    common_fields = set(old.keys()).intersection(ref.keys())
    for field in common_fields:
        if isinstance(old[field], dict):
            new[field] = update_dict(old[field], ref[field], {})
        else:
            new[field] = old[field]

    new_fields = set(ref.keys()).difference(common_fields)
    for field in new_fields:
        new[field] = ref[field]

    return new