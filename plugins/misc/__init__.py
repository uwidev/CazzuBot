"""Misc plugin package — small server utilities."""

from cazzubot import Plugin


class MiscPlugin(Plugin):
    name = "misc"
    extensions = ["plugins.misc.extension"]


plugin = MiscPlugin()
