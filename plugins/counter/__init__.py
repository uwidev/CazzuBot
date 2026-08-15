"""Counter plugin package."""

from cazzubot import Plugin

from . import db
from .extension import on_counter_expire


class CounterPlugin(Plugin):
    name = "counter"
    schema = db.SCHEMA
    extensions = ["plugins.counter.extension"]
    scheduled = {"counter": on_counter_expire}


plugin = CounterPlugin()
