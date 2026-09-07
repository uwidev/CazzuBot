"""Misc plugin package — small server utilities + shared brand emojis."""

from core import Plugin

from .asset import MiscAsset


class MiscPlugin(Plugin):
    """Small server utility command plugin."""

    name = "misc"
    extensions = ["plugins.misc.extension"]
    # the shared cirno emojis (the footer-icon provider for tip surfaces)
    asset_decl = MiscAsset


plugin = MiscPlugin()
