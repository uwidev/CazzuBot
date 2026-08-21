# How do I... add dependencies

A plugin that imports another plugin's modules (`from plugins.x import ...`
anywhere in its tree) must declare it with `depends_on`. This tells the
loader the other plugin must be loaded first — otherwise the import works
only by alphabetical luck.

## 1. Declare the dependency

In `plugins/<name>/__init__.py`, list the plugin names your feature needs:

```python
from cazzubot import Plugin


class BadgesPlugin(Plugin):
    name = "badges"
    depends_on = ("experience",)
```

The `experience` plugin does this in real code:

```python
# grants/consumes exp and queries ranks — levels and ranks must be loaded
depends_on = ("levels", "ranks")
```

## 2. What the loader does with it

`select_plugins` (`cazzubot/plugin.py`) resolves `depends_on` at boot:

- **Transitive closure** — `-s myfeature` loads `myfeature` *and* everything
  it depends on, recursively. `frogs` declares `("experience",)`, so
  `-s frogs` pulls in experience too.
- **Cycles load together** — plugins that depend on each other (experience ↔
  ranks) form one strongly-connected component and load as a unit.
- **Dependency order** — selected plugins load dependencies-first (topological
  sort), not alphabetical.
- **Unknown names fail boot** — a dependency that doesn't exist aborts with
  the list of available plugins.

## 3. Checks

- Every dependency must be a real, loaded plugin name.
- A disabled plugin also skips everything that transitively depends on it.
- Reach another plugin's *service* with care: shared services live on the bot
  (`bot.db`, `bot.settings`, …); keep `logic.py`/`db.py` free of `discord`
  imports (see **add a schema**).
