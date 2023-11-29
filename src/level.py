"""All things related to ext.levels which is to be public."""
import logging

import discord

from src import db, levels_helper, rank, user_json, utility
from src.cazzubot import CazzuBot


_log = logging.getLogger(__name__)


async def on_msg_handle_levels(
    bot: CazzuBot, message: discord.Message, level: utility.OldNew
):
    """Handle potential level ups from experience gain.

    Called from ext.experience. Returns (old, new) level
    """
    if level.new > level.old:
        gid = message.guild.id

        # If we ranked up, do not send level up, since rank up trumps level up.
        if not await rank.get_ranked_up(bot, level, gid):
            raw_json = await db.level.get_message(bot.pool, gid)
            embed_json = bot.json_decoder.decode(raw_json)

            member = message.author

            utility.deep_map(
                embed_json,
                formatter,
                member=member,
                level_old=level.old,
                level_new=level.new,
            )
            content, embed, embeds = user_json.prepare(embed_json)
            await message.channel.send(content, embed=embed, embeds=embeds)


def formatter(s: str, *, member, level_old=None, level_new=None):
    """Format string with rank-related placeholders.

    {avatar}
    {name} -> display_name
    {mention}
    {id}
    {level_old} -> previous level
    {level_new} -> new level
    """
    return s.format(
        avatar=member.avatar.url,
        name=member.display_name,
        mention=member.mention,
        id=member.id,
        level_old=level_old,
        level_new=level_new,
    )
