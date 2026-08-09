"""Experience plugin package."""

from cazzubot import Plugin

from . import db


class ExperiencePlugin(Plugin):
    name = "experience"
    schema = db.SCHEMA
    extensions = ["plugins.experience.cog"]
    # every awarded message presents level-ups and rank-ups, and exp top
    # queries rank roles — levels and ranks must be loaded with this
    depends_on = ("levels", "ranks")


plugin = ExperiencePlugin()
