"""Levels plugin package."""

from cazzubot import Plugin


class LevelsPlugin(Plugin):
    """Levels plugin — thresholds and level-up presentation."""

    name = "levels"
    extensions = ["plugins.levels.extension"]
    # the presenter checks rank thresholds via plugins.ranks.logic
    depends_on = ("ranks",)


plugin = LevelsPlugin()
