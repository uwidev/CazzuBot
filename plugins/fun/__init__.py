"""Fun plugin package."""

from cazzubot import Plugin


class FunPlugin(Plugin):
    name = "fun"
    extensions = ["plugins.fun.cog"]


plugin = FunPlugin()
