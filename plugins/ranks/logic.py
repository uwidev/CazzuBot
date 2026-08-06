"""Ranks plugin — shared rank-change logic (role integrity + rank-up messages)."""

import logging

import discord

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot
from cazzubot.models import WindowEnum
from cazzubot.utils import OldNew

from . import db as ranks_db
from .db import RankThreshold

_log = logging.getLogger(__name__)


def formatter(
    s: str,
    *,
    member: discord.Member,
    rank_old: discord.Role | None = None,
    rank_new: discord.Role | None = None,
    level_old: int | None = None,
    level_new: int | None = None,
) -> str:
    """Placeholders: {avatar} {name} {mention} {id} {rank_old} {rank_new}
    {level_old} {level_new}"""
    return s.format(
        avatar=member.display_avatar.url,
        name=member.display_name,
        mention=member.mention,
        id=member.id,
        rank_old=rank_old.mention if rank_old else None,
        rank_new=rank_new.mention if rank_new else None,
        level_old=level_old,
        level_new=level_new,
    )


def rank_difference(
    level: OldNew, thresholds: list[RankThreshold]
) -> tuple[OldNew, OldNew]:
    """(rid_old->rid_new, index_old->index_new) across the thresholds."""
    rid_new, idx_new = ranks_db.calc_min_rank(thresholds, level.new)
    rid_old, idx_old = ranks_db.calc_min_rank(thresholds, level.old)
    return OldNew(rid_old, rid_new), OldNew(idx_old, idx_new)


async def is_ranked_up(bot: CazzuBot, level: OldNew) -> bool:
    """True if going level.old -> level.new crosses a rank threshold."""
    thresholds = await ranks_db.get(bot.db)
    if not thresholds:
        return False
    _, index = rank_difference(level, thresholds)
    return index.new != index.old


async def handle_ranks(
    bot: CazzuBot,
    message: discord.Message,
    seasonal_level: OldNew,
    lifetime_level: OldNew,
    *,
    delete_after: int = 0,
) -> None:
    """Reconcile rank roles after an exp gain (v1 ``on_msg_handle_ranks``).

    Seasonal ranks notify on rank-up; lifetime ranks stay silent. Role
    integrity is enforced for both windows regardless.
    """
    seasonal_add, seasonal_remove = await _determine_rank_changes(
        bot,
        message,
        seasonal_level,
        WindowEnum.SEASONAL,
        notify=True,
        delete_after=delete_after,
    )
    lifetime_add, lifetime_remove = await _determine_rank_changes(
        bot,
        message,
        lifetime_level,
        WindowEnum.LIFETIME,
    )

    ranks_to_add = [r for r in seasonal_add + lifetime_add if r]
    ranks_to_remove = [r for r in seasonal_remove + lifetime_remove if r]

    member = message.author
    if not isinstance(member, discord.Member):
        return  # rank roles only exist for guild members
    if ranks_to_add:
        await member.add_roles(
            *ranks_to_add, reason="Rank up/Rank-role integrity"
        )
    if ranks_to_remove:
        await member.remove_roles(*ranks_to_remove)


async def _determine_rank_changes(
    bot: CazzuBot,
    message: discord.Message,
    level: OldNew,
    mode: WindowEnum,
    *,
    notify: bool = False,
    delete_after: int = 0,
) -> tuple[list[discord.Role], list[discord.Role]]:
    """Compute the roles to add/remove for one window's thresholds."""
    guild = message.guild
    if guild is None:
        return [], []

    if not await ranks_db.get_enabled(bot.settings, mode):
        return [], []

    thresholds = await ranks_db.get(bot.db, mode=mode)
    if not thresholds:
        return [], []

    member = message.author
    if not isinstance(member, discord.Member):
        return [], []
    rid, ind = rank_difference(level, thresholds)
    ranks = [guild.get_role(row.rid) for row in thresholds]

    # rank-up notification
    if notify and rid.new is not None and rid.new != rid.old:
        rank_new = guild.get_role(rid.new)
        if rank_new is not None:
            rank_old = (
                guild.get_role(rid.old) if rid.old is not None else None
            )
            msg_json = await ranks_db.get_message(bot.settings, mode)
            if msg_json:
                utils.deep_map(
                    msg_json,
                    formatter,
                    member=member,
                    rank_old=rank_old,
                    rank_new=rank_new,
                    level_old=level.old,
                    level_new=level.new,
                )
                await templates.send(
                    message.channel, msg_json, delete_after=delete_after
                )

    # role integrity
    if rid.new is not None:
        if await ranks_db.get_keep_old(bot.settings, mode):
            ranks_to_add = ranks[: ind.new + 1]
            ranks_to_remove = ranks[ind.new + 1 :]
        else:
            ranks_to_add = [guild.get_role(rid.new)]
            ranks_to_remove = ranks[: ind.new] + ranks[ind.new + 1 :]
    else:
        ranks_to_add = []
        ranks_to_remove = ranks

    ranks_to_add = [r for r in ranks_to_add if r and r not in member.roles]
    ranks_to_remove = [
        r for r in ranks_to_remove if r and r in member.roles
    ]
    return ranks_to_add, ranks_to_remove
