"""Levels plugin — shared level-up pipeline (message send + formatting)."""

import logging

import discord

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)

MESSAGE_KEY = "level.message"


def formatter(
    s: str,
    *,
    member: discord.Member,
    level_old: int | None = None,
    level_new: int | None = None,
) -> str:
    """Placeholders: {avatar} {name} {mention} {id} {level_old} {level_new}"""
    return s.format(
        avatar=member.display_avatar.url,
        name=member.display_name,
        mention=member.mention,
        id=member.id,
        level_old=level_old,
        level_new=level_new,
    )


async def handle_level_up(
    bot: CazzuBot,
    message: discord.Message,
    level: utils.OldNew,
    *,
    delete_after: int = 0,
) -> None:
    """Send the level-up message when a member levels up (unless ranked up)."""
    if level.new <= level.old:
        return

    from plugins.ranks.logic import is_ranked_up

    if await is_ranked_up(bot, level):
        return  # rank up trumps level up

    quiets: list[int] = await bot.settings.get("level.quiet", []) or []
    if message.channel.id in quiets:
        await message.add_reaction("🎉")
        return

    msg_json = await bot.settings.get(MESSAGE_KEY)
    if not msg_json:
        return

    utils.deep_map(
        msg_json,
        formatter,
        member=message.author,
        level_old=level.old,
        level_new=level.new,
    )
    await templates.send(
        message.channel, msg_json, delete_after=delete_after
    )
