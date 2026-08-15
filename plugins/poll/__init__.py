"""Poll plugin package."""

from cazzubot import Plugin

from . import db


class PollPlugin(Plugin):
    name = "poll"
    schema = db.SCHEMA
    extensions = ["plugins.poll.extension"]


plugin = PollPlugin()
