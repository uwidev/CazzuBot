"""Dev plugin package."""

from cazzubot import Plugin


class DevPlugin(Plugin):
    name = "dev"
    extensions = ["plugins.dev.cog"]


plugin = DevPlugin()
