"""Misc plugin package — small server utilities."""

from cazzubot import Plugin


class MiscPlugin(Plugin):
    """Small server utility command plugin."""

    name = "misc"
    extensions = ["plugins.misc.extension"]


plugin = MiscPlugin()
