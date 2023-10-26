"""All things related to ext.levels which is to be public."""
import logging

import discord

from src import levels_helper
from src.cazzubot import CazzuBot


_log = logging.getLogger(__name__)


async def on_msg_handle_levels(
    bot: CazzuBot, message: discord.Message, old_exp: int, new_exp: int
):
    """Handle potential level ups from experience gain.

    Called from ext.experience.
    """
    old_level = levels_helper.level_from_exp(old_exp)
    new_level = levels_helper.level_from_exp(new_exp)

    if new_level > old_level:
        _log.info(f"{message.author} has leveled up from {old_level} to {new_level}!")

    return new_level
