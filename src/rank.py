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
    rank_payload = await db.rank_threshold.get(bot.pool, gid)
    member = message.author

    rid_old, index_old, rid_new, index_new = rank_difference(
        bot, level_old, level_new, rank_payload
    )

    if rid_new is None:
        return

    rank_new = message.guild.get_role(rid_new)
    if not rank_new:  # role was deleted from guild
        err_msg = "On rank up, role was not found. Please contact an admin."
        await message.channel.send(err_msg)
        return

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

    if rank_new not in member.roles:  # Does not send rank up when correcting roles!
        await member.add_roles(rank_new, reason="Rank up")

    # remove all other roles than applied, convert to role, only remove existing
    rank_payload.pop(index_new)

    rids = [rank.get("rid") for rank in rank_payload]
    member_rids = [role.id for role in member.roles]
    del_roles = [member.guild.get_role(rid) for rid in rids if rid in member_rids]

    if del_roles:
        await member.remove_roles(*del_roles)


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
    return rank_difference(bot, level_old, level_new, rids)


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
