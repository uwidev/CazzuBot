"""All things related to ext.ranks which is to be public.

The original idea was to store member-rank data as a junction table, but rank can
trivially be derived from experience. We don't the junction table.
"""
import discord

from src import cazzubot, db, utility


async def on_msg_handle_ranks(
    bot: cazzubot.CazzuBot, message: discord.Message, level: int
):
    """Handle potential rank ups from level ups.

    Also keeps rank integrity regardless of level up.

    Called from ext.experience
    """
    ranks = await db.rank_threshold.get(bot.pool, message.guild.id)
    if not ranks:
        return

    rid, index = utility.calc_min_rank(ranks, level)

    if not rid:  # not even high enough level for any ranks
        return

    member = message.author
    role = message.guild.get_role(rid)
    await member.add_roles(role, reason="Rank up")

    # remove all other roles than applied, convert to role, only remove existing
    ranks.pop(index)
    del_roles = list(map(message.guild.get_role, (r["rid"] for r in ranks)))
    del_roles = filter(lambda r: r in member.roles, del_roles)
    if del_roles:
        await member.remove_roles(*del_roles)
