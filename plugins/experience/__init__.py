"""Experience plugin package."""

from cazzubot import Plugin

from . import db


class ExperiencePlugin(Plugin):
    name = "experience"
    schema = db.SCHEMA
    extensions = ["plugins.experience.cog"]


plugin = ExperiencePlugin()
