"""Levels plugin package."""

from cazzubot import Plugin


class LevelsPlugin(Plugin):
    name = "levels"
    extensions = ["plugins.levels.cog"]


plugin = LevelsPlugin()
