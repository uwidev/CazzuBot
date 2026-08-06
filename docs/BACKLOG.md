# Backlog

Deferred work, parked by request ("we will work on it later when I request it").
Pick these up when the owner asks; each item links to the discussion that
motivated it.

## 1. Plugin dependency policy — `depends_on`

Add `depends_on: list[str]` to the `Plugin` base (`cazzubot/plugin.py`). The
loader (`cazzubot/bot.py`) should:

- validate declared deps exist and load them first,
- fail fast with a clear error (not a confusing `ModuleNotFoundError`),
- respect the sandbox allowlist,
- detect dependency cycles.

## 2. `bot.get_plugin(name)` + optional-dependency degrade

Public accessor for loaded plugins (today callers reach into
`bot._plugin_by_name`, e.g. `plugins/dev/__init__.py`). Plus a degrade pattern
for optional dependencies: if a dependency is unloaded/hotswapped, dependents
skip their call instead of crashing.

## 3. Core event bus — `bot.events`

`emit`/`on`/`off` for bot-specific events (`member_leveled_up`,
`frog_captured`, …) so producers never know their consumers. Design decision
already made: the bus lives in **core** (`cazzubot/events.py`) — a generic
capability, not feature logic. Caveat to respect: events are less traceable
than direct calls and ordering isn't guaranteed — reach for them only when the
producer shouldn't know the consumer exists.

## 4. Event-bus consumer demo

One real consumer (e.g. a "level-up milestone" channel) to validate the bus
design before wider adoption.

## 5. Levels coupling cleanup

Move `handle_level_up`/`formatter` from `plugins/levels/cog.py` to
`plugins/levels/logic.py` (mirroring `plugins/ranks/logic.py`) so the
`experience` plugin imports service→service, not cog→cog. Prerequisite for #1
to be coherent.

## 6. Register persistent poll button view on boot

`plugins/poll/__init__.py`'s `PollView` is `timeout=None` but is never
re-registered via `bot.add_view`, so poll buttons die on bot restart (unlike
the counter button, which does register in `CounterPlugin.on_load`). Fix:
collect poll message ids (e.g. a `poll` table query in `PollPlugin.on_load`)
and `bot.add_view(PollView(bot, poll_id), message_id=mid)` for each, mirroring
the counter plugin.

> **Done** — `PollPlugin.on_load` re-registers every poll with a stored `mid`,
> and the Vote button got a stable `custom_id="poll:vote"` (without it,
> `bot.add_view` rejects the view as non-persistent and the random per-instance
> custom_id could never match the button baked into existing messages).

---

Context: these came out of the architecture discussion about three-tier
layering, plugin-to-plugin coupling (direct import vs data contract vs event
bus), and the levels kernel naming collision (`cazzubot/levels.py` vs
`plugins/levels/`). See docs/ARCHITECTURE.md and docs/PLUGINS.md. Item #6 was
parked during the reaction→button conversion (2026) to keep that change
focused.

---

> Other todos added by the developer.

## Counter DB rework
A single reaction on the counter should store the following:

mid,user,timestamp

Now we have a history of people who have pressed the button. From this, we can simplify the calls. The recent bakas can be a database call, grouped by user, summed. From this, we can get the most recent bakas.

We can also get the total count for the counter just by a sum call on the mid.

## Basedpyright cleanup follow-ups (review nits)

Non-blocking findings from the pre-commit review of the typing refactor
(`dfe217e`); parked here so they aren't lost.

1. `register_inktober` rejects threads — `plugins/fun/__init__.py` narrows
   the target with `isinstance(target, discord.abc.GuildChannel)`, but a
   `Thread` is a `Messageable`, not a `GuildChannel`; a thread-based
   inktober channel that previously worked now gets "Inktober needs a
   server channel". Include `discord.Thread` or narrow to
   `discord.abc.Messageable` instead.
2. Silent no-ops when `ctx.guild is None` — `unmute`/`unban`
   (`plugins/mod/__init__.py`) and `rank_clean` (`plugins/ranks/cog.py`)
   now `return` without feedback (previously a loud AttributeError). Send
   a short error message for friendliness.
3. `story_write` dropped its `ctx.message is not None` guard
   (`plugins/fun/__init__.py`) — safe in practice (interaction is None ⟺
   prefix command ⟹ message exists) but worth a comment or keeping the
   guard.
4. Redundant `content if content is not None else MISSING` in
   `plugins/frogs/factory.py` — discord.py treats `None` content as "not
   provided"; the dance is harmless but noisy, simplify to `content=content`.
