"""Contains the impplementation of levels systems.

A user's level is derived from a user's experience points. Because of this, levels do
not actually need to be stored internally.
"""

import logging
from enum import Enum, auto
from math import cos, pi

import discord
from discord.ext import commands

from src import levels_helper


async def setup(bot: commands.Bot):
    # await bot.add_cog(Levels(bot))
    pass
