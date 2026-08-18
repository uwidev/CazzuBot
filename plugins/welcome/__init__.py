"""Welcome plugin package."""

from cazzubot import Plugin


class WelcomePlugin(Plugin):
    """Welcome plugin — new-member message and approval/role handling."""

    name = "welcome"
    extensions = ["plugins.welcome.extension"]


plugin = WelcomePlugin()
