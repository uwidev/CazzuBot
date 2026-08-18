"""Dev plugin package."""

from cazzubot import Plugin


class DevPlugin(Plugin):
    """Owner/dev tooling: plugin reload/load/unload/enable/disable/list."""

    name = "dev"
    extensions = ["plugins.dev.extension"]


plugin = DevPlugin()
