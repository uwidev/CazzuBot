"""Ranks presentation — rank role mutations + rank-up messages (controller edge).

Thin: plan via ``plugins.ranks.logic`` (plain role ids), then resolve roles
from the cache and mutate via the rest client. The planning in ``logic.py``
stays.
"""

from __future__ import annotations

import logging

import hikari

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
    member: hikari.Member | hikari.User,
    channel_id: int,
    seasonal_level: OldNew,
    lifetime_level: OldNew,
    *,
    delete_after: float = 0,
) -> None:
    """Reconcile rank roles after an exp gain (v1 ``on_msg_handle_ranks``).

    Seasonal ranks notify on rank-up; lifetime ranks stay silent. Role
    integrity is enforced for both windows regardless.
    """
    member_role_ids = getattr(member, "role_ids", None)
    if member_role_ids is None:
        return  # rank roles only exist for guild members
    member_role_ids = list(map(int, member_role_ids))
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
                bot, member, channel_id, plan, mode, delete_after
            )
        add_ids += plan.add_ids
        remove_ids += plan.remove_ids

    guild_id = member.guild_id
    for rid in add_ids:
        role = bot.cache.get_role(rid)
        if role is not None:
            await bot.rest.add_role_to_member(
                guild_id, member.id, role.id, reason=_RANK_REASON
            )
    for rid in remove_ids:
        role = bot.cache.get_role(rid)
        if role is not None:
            await bot.rest.remove_role_from_member(
                guild_id, member.id, role.id
            )


async def _notify_rank_up(
    bot: CazzuBot,
    member: hikari.Member,
    channel_id: int,
    plan: RankPlan,
    mode: WindowEnum,
    delete_after: float,
) -> None:
    """Send the rank-up message when the new rank role actually exists."""
    rank_old = (
        bot.cache.get_role(plan.rid_old)
        if plan.rid_old is not None
        else None
    )
    rank_new = (
        bot.cache.get_role(plan.rid_new)
        if plan.rid_new is not None
        else None
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
    channel = bot.cache.get_guild_channel(channel_id)
    if channel is None or not hasattr(channel, "send"):
        return
    sent = await templates.send(channel, msg_json)
    if delete_after:
        utils.schedule_delete(bot, channel.id, sent.id, delete_after)
