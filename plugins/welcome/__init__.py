"""Welcome plugin package."""

from cazzubot import Plugin


class WelcomePlugin(Plugin):
    name = "welcome"
    extensions = ["plugins.welcome.extension"]


plugin = WelcomePlugin()
