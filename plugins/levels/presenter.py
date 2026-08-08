"""Levels presentation — the level-up side effects (controller edge).

Thin: decide via ``plugins.levels.logic``, then either react or send the
configured template. Replaced wholesale on a framework swap — everything
below the decisions in ``logic.py`` stays.
"""

from __future__ import annotations

import logging

import discord

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot
from cazzubot.utils import OldNew

from plugins.ranks.logic import is_ranked_up

from .logic import MESSAGE_KEY, LevelUpAction, decide_level_up, formatter

_log = logging.getLogger(__name__)

REACTION_EMOJI = "🎉"


async def present_level_up(
    bot: CazzuBot,
    message: discord.Message,
    level: OldNew,
    *,
    delete_after: int = 0,
) -> None:
    """Send the level-up message when a member levels up (unless ranked up)."""
    if level.new <= level.old:
        return  # hot path: every awarded message flows through here
    quiets: list[int] = await bot.settings.get("level.quiet", []) or []
    ranked_up = await is_ranked_up(bot.db, level)
    action = decide_level_up(
        level,
        ranked_up=ranked_up,
        channel_id=message.channel.id,
        quiet_ids=quiets,
    )
    if action is LevelUpAction.SKIP:
        return
    if action is LevelUpAction.REACTION:
        await message.add_reaction(REACTION_EMOJI)
        return

    msg_json = await bot.settings.get(MESSAGE_KEY)
    if not msg_json:
        return
    utils.deep_map(
        msg_json,
        formatter,
        member=utils.member_snapshot(message.author),
        level_old=level.old,
        level_new=level.new,
    )
    await templates.send(
        message.channel, msg_json, delete_after=delete_after
    )
