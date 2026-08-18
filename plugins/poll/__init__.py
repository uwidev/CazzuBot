"""Poll plugin package."""

from cazzubot import Plugin

from . import db


class PollPlugin(Plugin):
    """Poll plugin — app commands and the modal voting view."""

    name = "poll"
    schema = db.SCHEMA
    extensions = ["plugins.poll.extension"]


plugin = PollPlugin()
