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
    seasonal_add, seasonal_remove = await _on_msg_handle_ranks(
        bot, message, seasonal_level, notify=True
    )
    lifetime_add, lifetime_remove = await _on_msg_handle_ranks(
        bot, message, lifetime_level, WindowEnum.LIFETIME
    )

    ranks_to_add = [r for r in seasonal_add + lifetime_add if r]
    ranks_to_remove = [r for r in seasonal_remove + lifetime_remove if r]

    member = message.author
    if ranks_to_add:
        _log.debug("Rank_Integrity::Adding ranks %s", ranks_to_add)
        await member.add_roles(*ranks_to_add, reason="Rank up/Rank-role integrity")

    if ranks_to_remove:
        _log.debug("Rank_Integrity::Removing ranks %s", ranks_to_remove)
        await member.remove_roles(*ranks_to_remove)


async def _on_msg_handle_ranks(
    bot: CazzuBot,
    message: discord.Message,
    level: utility.OldNew,
    mode: WindowEnum = WindowEnum.SEASONAL,
    *,
    notify: bool = False,
) -> tuple[list[discord.Role], list[discord.Role]]:
    """Return a nested tuple containing the collection of ranks to add and remove.

    Is mainly a helper function to handle processing rank thresholds based on window.
    """
    gid = message.guild.id

    raw_rank_payload = await db.rank.get(bot.pool, gid, mode=mode)
    _, enabled, keep_old, embed_json = raw_rank_payload.values()

    if not enabled:
        return ([None], [None])

    rank_threshold_payload = await db.rank_threshold.get(bot.pool, gid, mode=mode)

    if len(rank_threshold_payload) == 0:  # no threshold ranks set yet
        return ([None], [None])

    member = message.author

    rid, ind = rank_difference(bot, level, rank_threshold_payload)
    rids = [row.get("rid") for row in rank_threshold_payload]
    ranks = [message.guild.get_role(rid) for rid in rids]

    # if rank up, send rank message
    if notify and rid.new != rid.old:
        seasonal_rank_new = message.guild.get_role(rid.new)
        if seasonal_rank_new is not None:  # if is None, role was deleted from guild
            rank_old = message.guild.get_role(rid.old)

            utility.deep_map(
                embed_json,
                formatter,
                member=member,
                rank_old=rank_old,
                rank_new=seasonal_rank_new,
                level_old=level.old,
                level_new=level.new,
            )

        content, embed, embeds = user_json.prepare(embed_json)
        await message.channel.send(content, embed=embed, embeds=embeds)

    # Ensure rank-role integreity
    if rid.new is not None:
        if keep_old:
            ranks_to_add = ranks[: ind.new + 1]
            ranks_to_remove = ranks[ind.new + 1 :]

        else:
            ranks_to_add = [seasonal_rank_new]
            remove_seasonal = ranks[: ind.new] + ranks[ind.new + 1 :]

            ranks_to_remove = remove_seasonal
    else:  # rid.new is None, meaning user is not high ranked enough for any ranks
        ranks_to_add = []
        ranks_to_remove = ranks

    # Filtering
    ranks_to_add = [r for r in ranks_to_add if r and r not in member.roles]
    ranks_to_remove = [r for r in ranks_to_remove if r and r in member.roles]

    return ranks_to_add, ranks_to_remove


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
) -> tuple[utility.OldNew, utility.OldNew]:
    """Return ranks corrosponding to given levels with their index to rids.

    Call this if you need to keep a reference to role ids, as the caller will need to
    pass this to this function. If you don't, consider the get_ranked_from_levels().

    Remember that it's possible for values to be None, which indicate a member is not
    high enough level for any ranks.
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

    Remember that it's possible for values to be None, which indicate a member is not
    high enough level for any ranks.
    """
    payload = rank_difference(bot, level.old, level.new, rids)

    if not payload:
        return False  # admin has yet to set up ranks

    _, index = payload

    return index.new != index.old


async def get_rank_difference(
    bot: CazzuBot,
    level: utility.OldNew,
    gid: int,
    *,
    mode: WindowEnum = WindowEnum.SEASONAL,
) -> tuple:
    """Fetch ranks from db, then call ranked_from_levels.

    Call this if you don't need to keep an internal reference to rids, and just need to
    figure out if ranked up from old->new level.
    """
    if not isinstance(gid, int):
        msg = f"gid must be a int, not of type {type(gid)}"
        raise TypeError(msg)

    rids = await db.rank_threshold.get(bot.pool, gid, mode=mode)

    if not rids:
        return None  # admin has yet to set up ranks

    return rank_difference(bot, level, rids)


async def get_ranked_up(bot: CazzuBot, level: utility.OldNew, gid: int):
    """Return true if going from level.old to level.new would result in a new rank.

    This is a database call. If you've already called the database, consider rank)
    """
    payload = await get_rank_difference(bot, level, gid)

    if not payload:
        return False  # admin has yet to set up ranks

    rid, index = payload
    return index.new != index.old


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
