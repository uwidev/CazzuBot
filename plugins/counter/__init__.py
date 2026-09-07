"""Counter plugin package."""

from core import Plugin

from . import db
from .extension import on_counter_expire


class CounterPlugin(Plugin):
    """The counter (\"baka button\") plugin."""

    name = "counter"
    schema = db.SCHEMA
    extensions = ["plugins.counter.extension"]
    scheduled = {"counter": on_counter_expire}


plugin = CounterPlugin()
