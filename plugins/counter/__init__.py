"""Counter plugin package."""

from cazzubot import Plugin

from . import db
from .cog import on_counter_expire


class CounterPlugin(Plugin):
    name = "counter"
    schema = db.SCHEMA
    extensions = ["plugins.counter.cog"]
    scheduled = {"counter": on_counter_expire}


plugin = CounterPlugin()
