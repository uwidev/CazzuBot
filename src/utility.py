"""General-purpose functions."""
import asyncio
import logging

from discord.ext import commands


_log = logging.getLogger("discord")
_log.setLevel(logging.INFO)


class ReadOnlyDict(dict):
    """Safeguard to prevent writing to DB templates."""

    def __setitem__(self, key, value):
        msg = "read-only dictionary, setting values is not supported"
        raise TypeError(msg)

    def __delitem__(self, key):
        msg = "read-only dict, deleting values is not supported"
        raise TypeError(msg)


def author_confirm(
    confirmation_msg: str = "Please confirm.", delete_after: bool = True
):
    """Force author to confirm that they want to run the command.

    Meant to be used as a decorator like so:

    @author_confirm(**kwargs)
    @command.command()
    async def command(ctx):
        ...
    """

    async def confirm(ctx: commands.Context) -> bool:
        author = ctx.author
        confirmation = await ctx.send(confirmation_msg)
        await confirmation.add_reaction("❌")
        await confirmation.add_reaction("✅")

        def check(reaction, user):
            if user.id == author.id and reaction.message.id == confirmation.id:
                if reaction.emoji in ["❌", "✅"]:
                    return True

            return False

        try:
            reaction, _ = await ctx.bot.wait_for(
                "reaction_add", check=check, timeout=10
            )
        except asyncio.TimeoutError:
            if delete_after:
                await confirmation.delete()
            return False

        if reaction.emoji == "❌":
            if delete_after:
                await confirmation.delete()
            return False

        if delete_after:
            await confirmation.delete()

        return True

    return commands.check(confirm)


def update_dict(old: dict, ref: dict) -> dict:
    """Return a new dict that matches reference dict, retaining values recursively.

    Does NOT remap fields, and is something that might need to be implemented
    in the future when making restructuring existing fields.

    Example:
    -------
        Input
        old = {'a': 3, 'b': {'x': 5}, 'c': 7}
        ref = {'a': 0, 'b': {'y': 0}, 'd': 2}

    Returns:
    -------
        {'a': 3, 'b': {'y': 0}, 'd': 2}
    """
    new = {}

    common_fields = set(old.keys()).intersection(ref.keys())
    for field in common_fields:
        if isinstance(old[field], dict):
            new[field] = update_dict(old[field], ref[field])
        else:
            new[field] = old[field]

    new_fields = set(ref.keys()).difference(common_fields)
    for field in new_fields:
        new[field] = ref[field]

    return new
