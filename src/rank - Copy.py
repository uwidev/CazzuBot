"""All things related to ext.ranks which is to be public.

The original idea was to store member-rank data as a junction table, but rank can
trivially be derived from experience. We don't the junction table.
"""
import logging

import discord
from asyncpg import Record

from src import db, user_json, utility
from src.cazzubot import CazzuBot
from src.db.table import WindowEnum


_log = logging.getLogger(__name__)


async def on_msg_handle_ranks(
    bot: CazzuBot,
    message: discord.Message,
    seasonal_level: utility.OldNew,
    lifetime_level: utility.OldNew,
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

    season_rank_threshold_payload = await db.rank_threshold.get(bot.pool, gid)
    life_rank_threshold_payload = await db.rank_threshold.get(
        bot.pool, gid, WindowEnum.LIFETIME
    )
    member = message.author

    seasonal_rid, seasonal_ind = rank_difference(
        bot, seasonal_level, season_rank_threshold_payload
    )
    lifetime_rid, lifetime_ind = rank_difference(
        bot, lifetime_level, life_rank_threshold_payload
    )

    _log.debug(f"{lifetime_ind=}, {lifetime_rid}")

    seasonal_rids = [row.get("rid") for row in season_rank_threshold_payload]
    seasonal_ranks = [message.guild.get_role(rid) for rid in seasonal_rids]
    lifetime_rids = [row.get("rid") for row in life_rank_threshold_payload]
    lifetime_ranks = [message.guild.get_role(rid) for rid in lifetime_rids]

    await handle_nonranker(seasonal_rid.new, seasonal_ranks, member)
    await handle_nonranker(lifetime_rid.new, lifetime_ranks, member)

    # if rank up, send rank message; does not apply role here
    if seasonal_rid.new != seasonal_rid.old:
        seasonal_rank_new = message.guild.get_role(seasonal_rid.new)
        if seasonal_rank_new is not None:  # if is None, role was deleted from guild
            rank_old = message.guild.get_role(seasonal_rid.old)
            embed_json = bot.json_decoder.decode(raw_json)

            utility.deep_map(
                embed_json,
                formatter,
                member=member,
                rank_old=rank_old,
                rank_new=seasonal_rank_new,
                level_old=seasonal_level.old,
                level_new=seasonal_level.new,
            )

        content, embed, embeds = user_json.prepare(embed_json)
        await message.channel.send(content, embed=embed, embeds=embeds)

    lifetime_rank_new = message.guild.get_role(seasonal_rid.new)
    if not lifetime_rank_new:
        return  # rank-role was deleted from guild

    if keep_old and not all(seasonal_ranks):
        return  # rank-role was deleted from the guild

    # Ensure rank-role integreity
    if keep_old:
        ranks_to_add = (
            seasonal_ranks[: seasonal_ind.new + 1]
            + lifetime_ranks[: lifetime_ind.new + 1]
        )

        _log.debug(f"{lifetime_ranks=}, {ranks_to_add=}")

        ranks_to_remove = (
            seasonal_ranks[seasonal_ind.new + 1 :]
            + lifetime_ranks[lifetime_ind.new + 1 :]
        )

    else:
        ranks_to_add = [seasonal_rank_new, lifetime_rank_new]
        remove_seasonal = (
            seasonal_ranks[: seasonal_ind.new] + seasonal_ranks[seasonal_ind.new + 1 :]
        )
        remove_lifetime = (
            lifetime_ranks[: lifetime_ind.new] + lifetime_rank_new[lifetime_ind + 1]
        )
        ranks_to_remove = remove_seasonal + remove_lifetime

    ranks_to_add = [r for r in ranks_to_add if r and r not in member.roles]
    ranks_to_remove = [r for r in ranks_to_remove if r and r in member.roles]

    _log.debug(f"{ranks_to_add=}, {ranks_to_remove=}")

    if ranks_to_add:
        _log.debug("Rank_Integrity::Adding ranks %s", ranks_to_add)
        await member.add_roles(*ranks_to_add, reason="Rank up/Rank-role integrity")

    if ranks_to_remove:
        _log.debug("Rank_Integrity::Removing ranks %s", ranks_to_remove)
        await member.remove_roles(*ranks_to_remove)


async def handle_nonranker(rid_new: int, ranks: [discord.Role], member: discord.Member):
    """Handle when a user is not high enough level for any rank.

    Refactored to allow seasonal and lifetime without repeating code.
    """
    if rid_new is None:  # member isn't high enough for any ranks
        ranks_to_remove = [rank for rank in ranks if rank in member.roles]
        if ranks_to_remove:
            _log.debug("Rank_Integrity::Removing ranks %s", ranks_to_remove)
            await member.remove_roles(*ranks_to_remove, reason="Rank-role integrity")
        return  # to ensure rank-role integrity


async def add_up_to_rank(
    bot: CazzuBot, member: discord.Member, ranks: list[discord.Role], rank_ind: int
):
    """Add ranks to member from rid index 0 to rank_ind."""
    ranks_to_add = ranks[: rank_ind + 1]
    ranks_to_add = [rank for rank in ranks_to_add if rank not in member.roles and rank]

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
    bot: CazzuBot, level: utility.OldNew, rids: list[Record]
) -> (utility.OldNew, utility.OldNew):
    """Return ranks corrosponding to given levels with their index to rids.

    (rid_old, index_old, rid_new, index_new)

    Call this if you need to keep a reference to role ids, as the caller will need to
    pass this to this function. If you don't, consider the get_ranked_from_levels().
    """
    if not isinstance(rids, list):
        msg = f"rids must be a list, not of type {type(rids)}"
        raise TypeError(msg)

    rid_new, index_new = calc_min_rank(rids, level.new)
    rid_old, index_old = calc_min_rank(rids, level.old)

    # return rid_old, index_old, rid_new, index_new
    return utility.OldNew(rid_old, rid_new), utility.OldNew(index_old, index_new)


def ranked_up(bot: CazzuBot, level: utility.OldNew, rids: list[Record]):
    """Return true if going from level_old to level_new would result in a new rank.

    Requires that you've already made a database call to get the ranked ids. If you
    haven't made a database call, consider get_ranked_up().
    """
    payload = rank_difference(bot, level.old, level.new, rids)

    if not payload:
        return False  # admin has yet to set up ranks

    _, index = payload

    return index.new != index.old


async def get_rank_difference(bot: CazzuBot, level: utility.OldNew, gid: int) -> tuple:
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

    return rank_difference(bot, level.old, level.new, rids)


async def get_ranked_up(bot: CazzuBot, level: utility.OldNew, gid: int):
    """Return true if going from level.old to level.new would result in a new rank.

    This is a database call. If you've already called the database, consider rank)
    """
    payload = await get_rank_difference(bot, level.old, level.new, gid)

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
