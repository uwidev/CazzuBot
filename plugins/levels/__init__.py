"""Levels plugin package."""

from cazzubot import Plugin


class LevelsPlugin(Plugin):
    name = "levels"
    extensions = ["plugins.levels.cog"]
    # the presenter checks rank thresholds via plugins.ranks.logic
    depends_on = ("ranks",)


plugin = LevelsPlugin()
