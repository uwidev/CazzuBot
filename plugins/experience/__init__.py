"""Experience plugin package."""

from cazzubot import Plugin

from . import db
from .cog import ExperienceCog


class ExperiencePlugin(Plugin):
    name = "experience"
    schema = db.SCHEMA
    cogs = [ExperienceCog]


plugin = ExperiencePlugin()
