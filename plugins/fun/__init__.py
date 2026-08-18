"""Fun plugin package."""

from cazzubot import Plugin


class FunPlugin(Plugin):
    """Meme and fun command plugin."""

    name = "fun"
    extensions = ["plugins.fun.extension"]


plugin = FunPlugin()
