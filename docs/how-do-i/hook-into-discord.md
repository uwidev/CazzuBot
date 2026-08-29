How do I… hook into Discord (extensions)
========================================

Commands and listeners live in a **lightbulb extension module** — one per
plugin, usually `plugins/<name>/extension.py`. Point the plugin at it with
`extensions`.


1. Declare the extension
------------------------

`plugins/<name>/__init__.py`:

~~~~ python
class BadgesPlugin(Plugin):
    name = "badges"
    extensions = ["plugins.badges.extension"]
~~~~

The module defines a top-level `loader = lightbulb.Loader()`; everything you
register on it gets loaded with the plugin.


2. Slash commands
-----------------

~~~~ python
import lightbulb

loader = lightbulb.Loader()


@loader.command
class Badges(
    lightbulb.SlashCommand, name="badges", description="Show badges."
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = ctx.client.app  # the CazzuBot
        await ctx.respond("...")
~~~~

Group subcommands use `lightbulb.Group` (see `plugins/counter/extension.py`).


3. Listeners
------------

Guild-scoped listeners **must** use `guild_listener`, never bare
`@loader.listener` — the bot serves one guild and drops other-guild/DM
events for you:

~~~~ python
from cazzubot.listeners import guild_listener


@guild_listener(loader, hikari.MessageCreateEvent)
async def on_message(event: hikari.MessageCreateEvent) -> None:
    bot = event.app  # the CazzuBot
    ...
~~~~

Persistent buttons/modals use a component-interaction listener with a fixed
custom id — see the baka button in `plugins/counter/extension.py`.


4. Reaching the bot
-------------------

 -  From a command: `ctx.client.app` (the `CazzuBot`).
 -  From a listener: `event.app`.
 -  Services hang off it: `bot.db`, `bot.settings`, `bot.scheduler`,
    `bot.config`, `bot.guild`.


5. Reload without a restart
---------------------------

If you only changed an extension, hot-reload it from the dev plugin:

~~~~
/plugin reload badges
~~~~

Schema or `__init__.py` changes still need a restart.
