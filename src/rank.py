"""All things related to ext.ranks which is to be public.

The original idea was to store member-rank data as a junction table, but rank can
trivially be derived from experience. We don't the junction table.
"""
import logging

import discord

from src import db, user_json, utility
from src.cazzubot import CazzuBot


_log = logging.getLogger(__name__)


async def on_msg_handle_ranks(
    bot: CazzuBot, message: discord.Message, level_old: int, level_new: int
):
    """Handle potential rank ups from level ups.

    Also keeps rank integrity regardless of level up.

    Called from ext.experience
    """
    gid = message.guild.id
    rank_ids = await db.rank_threshold.get(bot.pool, gid)
    member = message.author
    rids = await db.rank_threshold.get(bot.pool, gid)

    has_ranked = ranked_from_levels(bot, level_old, level_new, rids)
    if not has_ranked:
        return  # no rank up if both return
    rid_old, index_old, rid_new, index_new = has_ranked

    rank_new = message.guild.get_role(rid_new)

    if rid_new != rid_old:
        rank_old = message.guild.get_role(rid_old)
        raw_json = await db.rank.get_message(bot.pool, gid)
        embed_json = bot.json_decoder.decode(raw_json)

        utility.deep_map(
            embed_json,
            formatter,
            member=member,
            rank_old=rank_old,
            rank_new=rank_new,
            level_old=level_old,
            level_new=level_new,
        )

        content, embed, embeds = user_json.prepare(embed_json)
        await message.channel.send(content, embed=embed, embeds=embeds)

    if rank_new not in member.roles:
        await member.add_roles(rank_new, reason="Rank up")

    # remove all other roles than applied, convert to role, only remove existing
    rank_ids.pop(index_new)

    del_roles = [
        await member.guild.get_role(rank_id)
        for rank_id in rank_ids
        if rank_id in member.roles
    ]
    if del_roles:
        await member.remove_roles(*del_roles)


def ranked_from_levels(
    bot: CazzuBot, level_old: int, level_new: int, rids: list[int] = None
) -> tuple | bool:
    """Return a tuple of rid info if different levels results in new rank.

    (rid_old, index_old, rid_new, index_new)

    Returns False ranks not different.

    Call this if you need to keep a reference to role ids, as the caller will need to
    pass this to this function. If you don't, consider the get_ranked_from_levels().
    """
    if not isinstance(rids, list):
        msg = f"rids must be a list, not of type {type(rids)}"
        raise TypeError(msg)

    if not rids:
        return False

    rid_new, index_new = utility.calc_min_rank(rids, level_new)
    if not rid_new:  # not even high enough level for any ranks
        return False

    rid_old, index_old = utility.calc_min_rank(rids, level_old)
    if rid_new != rid_old:
        return rid_old, index_old, rid_new, index_new

    return False


async def get_ranked_from_levels(
    bot: CazzuBot, level_old: int, level_new: int, gid: int
) -> tuple | bool:
    """Fetch ranks from db, then call ranked_from_levels.

    Call this if you don't need to keep an internal reference to rids, and just need to
    figure out if ranked up from old->new level.
    """
    if not isinstance(gid, int):
        msg = f"gid must be a int, not of type {type(gid)}"
        raise TypeError(msg)

    rids = await db.rank_threshold.get(bot.pool, gid)
    return ranked_from_levels(bot, level_old, level_new, rids)


def formatter(
    s: str,
    *,
    member,
    rank_old: discord.Role = None,
    rank_new: discord.Role = None,
    level_old: int = None,
    level_new: int = None,
):
    """Format string with rank-related placeholders.

    {avatar}
    {name} -> display_name
    {mention}
    {id}
    {rank_old} -> previous rank
    {rank_new} -> new rank
    {level_old} -> previous level
    {level_new} -> new level
    """
    rank_old = rank_old.mention if rank_old else None  # edge case, no argument
    rank_new = rank_new.mention if rank_new else None

    return s.format(
        avatar=member.avatar.url,
        name=member.display_name,
        mention=member.mention,
        id=member.id,
        rank_old=rank_old,
        rank_new=rank_new,
        level_old=level_old,
        level_new=level_new,
    )
