# How do I... add a command group with admin gating

A group bundles related subcommands under one name. Gated groups are hidden
from non-admins via `default_member_permissions`; subcommands can't carry that
field, so every mutating subcommand also gets a check hook.

## 1. Declare the group and register subcommands

`plugins/<name>/extension.py`:

```python
import lightbulb

loader = lightbulb.Loader()

badges = lightbulb.Group(
    "badges",
    "Badge management.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)


@badges.register
class Give(
    lightbulb.SlashCommand,
    name="give",
    description="Grant a badge.",
    hooks=[utils.OWNER_ONLY],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        ...


loader.command(badges)
```

The `board` plugin does exactly this (`plugins/board/extension.py`): the
group owns the permission, and `Scrape` carries a `hooks=[utils.OWNER_ONLY]`
check on top.

## 2. Subgroups

Nest further with `group.subgroup(name, description)`:

```python
welcome = lightbulb.Group(
    "welcome", "Welcome message settings.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)
welcome_set = welcome.subgroup("set", "Set welcome settings.")
```

See `plugins/welcome/extension.py`.

## 3. Gating rules

- Fully-gated groups: `board`/`counter`/`level`/`rank`/`welcome`/`poll`/`misc`/`story`.
- Mixed groups (`frog`/`exp`/`mod`) stay visible because subcommands can't
  carry the field — but every mutating subcommand is check-gated.
- `tests/core/test_command_guards.py` sweeps the whole command tree: every
  command must be hidden, hook-checked, or explicitly user-facing. Run it.

## 4. Checks

```sh
uv run pytest tests/core/test_command_guards.py tests/integration/test_guard_driver.py
```
