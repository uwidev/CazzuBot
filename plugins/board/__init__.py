"""Board plugin package — weekly image scrape → numbered grid.

Core flow: ``/board scrape`` collects a week's image attachments (hash
dedup), ``/board post`` stitches them into a numbered grid and posts it in
the invoking channel. The weekly automation (scheduled cadence, poll
tie-in, winner banner) is backlogged.
"""

from cazzubot import Plugin

from . import db


class BoardPlugin(Plugin):
    name = "board"
    schema = db.SCHEMA
    extensions = ["plugins.board.cog"]


plugin = BoardPlugin()
