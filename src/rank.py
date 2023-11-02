"""All things related to ext.ranks which is to be public.

The original idea was to store member-rank data as a junction table, but rank can
trivially be derived from experience. We don't the junction table.
"""
import logging

import discord
from asyncpg import Record

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

    raw_rank_payload = await db.rank.get(bot.pool, gid)
    _, enabled, keep_old, raw_json = raw_rank_payload.values()

    if not enabled:
        return

    rank_threshold_payload = await db.rank_threshold.get(bot.pool, gid)
    member = message.author

    rid_old, index_old, rid_new, index_new = rank_difference(
        bot, level_old, level_new, rank_threshold_payload
    )
    rids = [p.get("rid") for p in rank_threshold_payload]
    ranks = [message.guild.get_role(rid) for rid in rids]

    if rid_new is None:  # member isn't high enough for any ranks
        _log.info("Not high enough for ranks")
        ranks_to_remove = [rank for rank in ranks if rank in member.roles]
        if ranks_to_remove:
            _log.debug("Rank_Integrity::Removing ranks %s", ranks_to_remove)
            await member.remove_roles(*ranks_to_remove, reason="Rank-role integrity")
        return  # to ensure rank-role integrity

    rank_new = message.guild.get_role(rid_new)
    if not rank_new:
        return  # rank-role was deleted from guild

    if keep_old and not all(ranks):
        return  # rank-role was deleted from the guild

    if rid_new != rid_old:  # if rank up, send rank message
        rank_old = message.guild.get_role(rid_old)
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

    # Ensure rank-role integreity
    if keep_old:
        await add_up_to_rank(bot, member, ranks, index_new)
        await remove_beyond_rank(bot, member, ranks, index_new)
    else:
        _log.debug("Rank_Integrity::Adding ranks %s", [rank_new])
        await member.add_roles(rank_new, reason="Rank up")
        await remove_ranks_except(bot, member, ranks, index_new)


async def add_up_to_rank(
    bot: CazzuBot, member: discord.Member, ranks: list[discord.Role], rank_ind: int
):
    """Add ranks to member from rid index 0 to rank_ind."""
    ranks_to_add = ranks[: rank_ind + 1]
    ranks_to_add = [rank for rank in ranks_to_add if rank not in member.roles]

    if ranks_to_add:
        _log.debug("Rank_Integrity::Adding ranks %s", ranks_to_add)
        await member.add_roles(*ranks_to_add, reason="Rank up/Rank-role integrity")


async def remove_beyond_rank(
    bot: CazzuBot, member: discord.Member, ranks: list[discord.Role], rank_ind: int
):
    """Remove ranks from rank_ind+1 to -1."""
    if rank_ind >= len(ranks) - 1:
        return  # member is maxed rank, no need to remove other ranks
    ranks_to_remove = ranks[rank_ind + 1 :]
    ranks_to_remove = [rank for rank in ranks_to_remove if rank in member.roles]

    if ranks_to_remove:
        _log.debug("Rank_Integrity::Removing ranks %s", ranks_to_remove)
        await member.remove_roles(*ranks_to_remove)


async def remove_ranks_except(
    bot: CazzuBot, member: discord.Member, ranks: list[discord.Role], rank_ind: int
):
    """Remove all ranks except rank_ind."""
    ranks_to_remove = ranks.copy()
    ranks_to_remove.pop(rank_ind)
    ranks_to_remove = [rank for rank in ranks_to_remove if rank in member.roles]

    if ranks_to_remove:
        _log.debug(f"Rank_Integrity::Removing ranks {ranks_to_remove}")
        await member.remove_roles(*ranks_to_remove)


def calc_min_rank(rank_thresholds: list[Record], level) -> tuple[int, int]:
    """Naively determine rank based on level from list of records.

    Returns (rank_id, rank_index). (None, None) if not high enough for any rank.
    """
    if level < rank_thresholds[0]["threshold"]:
        return None, None

    for i in range(1, len(rank_thresholds)):
        if level < rank_thresholds[i]["threshold"]:
            return rank_thresholds[i - 1]["rid"], i - 1

    return rank_thresholds[-1]["rid"], len(rank_thresholds) - 1


def rank_difference(
    bot: CazzuBot, level_old: int, level_new: int, rids: list[Record]
) -> tuple | bool:
    """Return ranks corrosponding to given levels with their index to rids.

    (rid_old, index_old, rid_new, index_new)

    Call this if you need to keep a reference to role ids, as the caller will need to
    pass this to this function. If you don't, consider the get_ranked_from_levels().
    """
    if not isinstance(rids, list):
        msg = f"rids must be a list, not of type {type(rids)}"
        raise TypeError(msg)

    rid_new, index_new = calc_min_rank(rids, level_new)
    rid_old, index_old = calc_min_rank(rids, level_old)

    return rid_old, index_old, rid_new, index_new


def ranked_up(bot: CazzuBot, level_old: int, level_new: int, rids: list[Record]):
    """Return true if going from level_old to level_new would result in a new rank.

    Requires that you've already made a database call to get the ranked ids. If you
    haven't made a database call, consider get_ranked_up().
    """
    payload = rank_difference(bot, level_old, level_new, rids)

    if not payload:
        return False  # admin has yet to set up ranks

    _, index_old, _, index_new = payload
    return index_new != index_old


async def get_rank_difference(
    bot: CazzuBot, level_old: int, level_new: int, gid: int
) -> tuple:
    """Fetch ranks from db, then call ranked_from_levels.

    Call this if you don't need to keep an internal reference to rids, and just need to
    figure out if ranked up from old->new level.
    """
    if not isinstance(gid, int):
        msg = f"gid must be a int, not of type {type(gid)}"
        raise TypeError(msg)

    rids = await db.rank_threshold.get(bot.pool, gid)

    if not rids:
        return None  # admin has yet to set up ranks

    return rank_difference(bot, level_old, level_new, rids)


async def get_ranked_up(bot: CazzuBot, level_old: int, level_new: int, gid: int):
    """Return true if going from level_old to level_new would result in a new rank.

    This is a database call. If you've already called the database, consider rank)
    """
    payload = await get_rank_difference(bot, level_old, level_new, gid)

    if not payload:
        return False  # admin has yet to set up ranks

    _, index_old, _, index_new = payload
    return index_new != index_old


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
