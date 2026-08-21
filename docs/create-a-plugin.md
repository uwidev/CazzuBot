# How do I... create a new plugin

A plugin is a self-contained package under `plugins/`. The bot discovers it,
applies its schema, registers its extensions, and arms its scheduled tasks —
no central registration.

This page is the minimal path. It follows the `counter` plugin
(`plugins/counter/`), the smallest one, as a reference.

## 1. Create the folder

```
plugins/<name>/
    __init__.py     -> defines plugin = MyPlugin()
    <name>.py       -> optional: schema + DB helpers
    extension.py    -> optional: slash commands and listeners
```

Pick a short, unique `name`. This example uses **`badges`**.

## 2. Write `plugins/badges/__init__.py`

```python
"""Badges plugin package."""

from cazzubot import Plugin

from . import db


class BadgesPlugin(Plugin):
    """A badges plugin."""

    name = "badges"
    schema = db.SCHEMA
    extensions = ["plugins.badges.extension"]


plugin = BadgesPlugin()
```

That's everything the loader needs to pick it up.

## 3. Add optional bridges (as needed)

| Field                   | What it does                                             | Example                        |
| ----------------------- | -------------------------------------------------------- | ------------------------------ |
| `schema`                | list of idempotent DDL statements (tables/columns)       | `db.SCHEMA`                    |
| `extensions`            | import paths of lightbulb extension modules              | `["plugins.badges.extension"]` |
| `scheduled`             | tag → handler `(bot, payload)` for the central scheduler | `{"badges": on_..._due}`       |
| `depends_on`            | plugin names this one needs loaded first                 | `("experience",)`              |
| `asset_decl`            | enum of assets this plugin declares                      | see add-an-asset               |
| `item_decl`             | enum of items this plugin declares                       | see add-an-item                |
| `on_load` / `on_unload` | async hooks after/before load                            | reset state, re-arm tasks      |

```python
class BadgesPlugin(Plugin):
    name = "badges"
    schema = db.SCHEMA
    extensions = ["plugins.badges.extension"]
    depends_on = ("experience",)
```

## 4. Add a slash command (extension module)

`plugins/badges/extension.py`:

```python
import lightbulb

from cazzubot import utils

loader = lightbulb.Loader()


@loader.command
class Badges(lightbulb.SlashCommand, name="badges", description="Show badges."):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = utils.bot_from(ctx)
        ...
```

## 5. Run it

```sh
uv run python main.py -d -s badges
```

This loads only `badges` (plus its dependencies) into the development guild.
Then test the full set normally with `uv run python main.py -d`.

## Checks

- `uv run ruff check .` — lint.
- `uv run pytest` — the suite boots every plugin, so adding one that fails to
  load breaks the `full_bot` fixture; fix it.
- New guild-scoped listeners must use `cazzubot.listeners.guild_listener`, not
  bare `@loader.listener` — the bot serves one guild.
