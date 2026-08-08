"""Ranks presentation — rank role mutations + rank-up messages (controller edge).

Thin: plan via ``plugins.ranks.logic`` (plain role ids), then resolve roles
on the guild and mutate. Replaced wholesale on a framework swap — the
planning in ``logic.py`` stays.
"""

from __future__ import annotations

import logging

import discord

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot
from cazzubot.models import WindowEnum
from cazzubot.utils import OldNew

from . import db as ranks_db
from .logic import RankPlan, formatter, plan_rank_changes

_log = logging.getLogger(__name__)

_RANK_REASON = "Rank up/Rank-role integrity"


async def present_ranks(
    bot: CazzuBot,
    member: discord.Member | discord.User,
    channel: discord.abc.Messageable,
    seasonal_level: OldNew,
    lifetime_level: OldNew,
    *,
    delete_after: int = 0,
) -> None:
    """Reconcile rank roles after an exp gain (v1 ``on_msg_handle_ranks``).

    Seasonal ranks notify on rank-up; lifetime ranks stay silent. Role
    integrity is enforced for both windows regardless.
    """
    if not isinstance(member, discord.Member):
        return  # rank roles only exist for guild members

    member_role_ids = [r.id for r in member.roles]
    add_ids: list[int] = []
    remove_ids: list[int] = []
    for mode, level, notify in (
        (WindowEnum.SEASONAL, seasonal_level, True),
        (WindowEnum.LIFETIME, lifetime_level, False),
    ):
        if not await ranks_db.get_enabled(bot.settings, mode):
            continue
        thresholds = await ranks_db.get(bot.db, mode=mode)
        if not thresholds:
            continue
        plan = plan_rank_changes(
            level,
            thresholds,
            keep_old=await ranks_db.get_keep_old(bot.settings, mode),
            notify=notify,
            member_role_ids=member_role_ids,
        )
        if plan.notify and plan.rid_new is not None:
            await _notify_rank_up(
                bot, member, channel, plan, mode, delete_after
            )
        add_ids += plan.add_ids
        remove_ids += plan.remove_ids

    guild = member.guild
    ranks_to_add = [guild.get_role(i) for i in add_ids]
    ranks_to_remove = [guild.get_role(i) for i in remove_ids]
    ranks_to_add = [r for r in ranks_to_add if r]
    ranks_to_remove = [r for r in ranks_to_remove if r]
    if ranks_to_add:
        await member.add_roles(*ranks_to_add, reason=_RANK_REASON)
    if ranks_to_remove:
        await member.remove_roles(*ranks_to_remove)


async def _notify_rank_up(
    bot: CazzuBot,
    member: discord.Member,
    channel: discord.abc.Messageable,
    plan: RankPlan,
    mode: WindowEnum,
    delete_after: int,
) -> None:
    """Send the rank-up message when the new rank role actually exists."""
    guild = member.guild
    rank_old = (
        guild.get_role(plan.rid_old) if plan.rid_old is not None else None
    )
    rank_new = (
        guild.get_role(plan.rid_new) if plan.rid_new is not None else None
    )
    if rank_new is None:
        return
    msg_json = await ranks_db.get_message(bot.settings, mode)
    if not msg_json:
        return
    utils.deep_map(
        msg_json,
        formatter,
        member=utils.member_snapshot(member),
        rank_old=rank_old.mention if rank_old else None,
        rank_new=rank_new.mention if rank_new else None,
        level_old=plan.level_old,
        level_new=plan.level_new,
    )
    await templates.send(channel, msg_json, delete_after=delete_after)
