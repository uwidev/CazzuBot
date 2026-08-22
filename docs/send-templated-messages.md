# How do I... send templated messages

Admins can configure message JSON (level-ups, rank-ups, frog spawns) as
`{placeholder}` templates. Route these through `cazzubot.templates` and
surface command state through `bot.window`.

## 1. Validate and store a template

`verify` parses + jsonschema-validates admin-supplied JSON and dry-runs the
formatter. It's pure CPU — don't `await` it:

```python
from cazzubot import templates, utils


def formatter(s, *, member: MemberSnapshot):
    return utils.format_member(s, member)


decoded = templates.verify(
    raw, formatter, member=member
)  # UserInputError on bad
await bot.settings.set("badges.message", decoded)
```

## 2. Send it

`send` delivers a stored dict to any target (a channel or a lightbulb
`Context`), formatting placeholders and setting least-permissive mentions:

```python
raw = await bot.settings.get("badges.message")
await templates.send(ctx, raw)  # ctx is a lightbulb Context
await templates.send(channel, raw)  # or any hikari channel
```

`prepare(message)` returns `(content, embed, embeds)` as **plain JSON** — use
it in service code to decide *whether* to send without touching discord.

## 3. Command feedback via the window

For command-local status, use the window — it buffers and flushes once, and
flips nothing until end-of-command:

```python
from cazzubot.window import command_window

async with command_window(ctx) as window:
    window.info("fetching...")
    await window.flush()  # only before blocking work
    window.success("done")
```

One-off: `await window_success(ctx, "badge granted")`. Levels: `debug` /
`info` (plain), `success` (`✓`), `warn` (`⚠︎`), `error` (`✖`). Prefer the
window over emoji-reaction feedback or raw `logging` for user-facing state.

## 4. Full shape

- `templates.verify(raw, formatter, **kwargs)` → validated dict (sync).
- `templates.prepare(message)` → `(content, embed, embeds)` (plain JSON).
- `templates.send(destination, message, **kwargs)` → delivered message.
