# How do I... read & write settings

`bot.settings` is a JSON key-value store for one guild. Use it for any
per-plugin knob administrators configure.

## 1. Get and set

Keys are namespaced with your plugin name to avoid collisions:

```python
# in a command or listener with the CazzuBot
enabled = await bot.settings.get("badges.enabled", False)
await bot.settings.set("badges.default_rid", 123456789)
await bot.settings.delete("badges.old_key")
```

Values are JSON-serialized, so `set` accepts scalars, lists and dicts:

```python
await bot.settings.set("badges.win_locations", ["east", "west"])
```

The `welcome` plugin reads most of its state this way
(`plugins/welcome/extension.py`): `welcome.enabled`, `welcome.cid`,
`welcome.message`, `welcome.mode`, plus role ids.

## 2. Persisted where?

The `settings` table in the same per-guild sqlite file as everything else —
values survive restarts. Timestamps as ISO-8601 UTC, enums as their `.value`
string.

## 3. Command-local vs admin panel

A command that mutates settings (see `welcome set` subcommands) reads the
current value, applies the change, then writes it back and confirms via the
window:

```python
await bot.settings.set("welcome.enabled", self.enabled)
window.success("welcome enabled")
```

See **send templated messages** and **write a plugin test** for the window
and for testing settings-backed commands.

## 4. Checks

- Prefix every key with your plugin name — the store is shared.
- `bot.config` is *boot* config (token, guild, debug) — different from
  runtime settings. Don't put user-tunable state there.
