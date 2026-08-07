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

> **Done** — `MESSAGE_KEY`/`formatter`/`handle_level_up` live in
> `plugins/levels/logic.py`; the cog is config-only and re-imports them.
> `experience` and `scripts/functest.py` import from `plugins.levels.logic`,
> so no plugin reaches into another plugin's cog (mirrors `ranks/logic.py`).

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

## 7. Enforce Controller → Service → Repository within plugins

Codify the existing (informal) per-feature layering — `cog.py` = controller,
`logic.py`/`factory.py` = service, `db.py` = repository. The split is already
the `PLUGINS.md` convention and most features have the files; what's missing
is the boundary discipline at the service layer.

- **Boundary rule:** service functions take `db`/`settings` + plain values +
  injected `now`; **no stateful discord objects** (`Member`, `User`, `Message`,
  `Guild`, `Channel`, `Role`, `Asset`, `Interaction`, `Bot`) past the
  controller edge. Pure-data value types (`discord.Embed`, `Permissions`,
  `Colour`) are fine — constructible offline, unit-testable. Service
  vocabulary should trend toward `cazzubot.models` dataclasses (ties into the
  LSP-hints item below). Development may stay monolithic per feature; a
  feature "settles" into CSR via test-then-extract.
- **Extraction order, each step under characterization tests first:**
  1. `experience._award_exp` (`plugins/experience/cog.py`) — the biggest win;
     returns a plain result, presentation moves to the controller (or later an
     event-bus subscriber, see #3).
     > **Done** — `plugins/experience/logic.py`: `award_exp(db, *, uid, now)`;
     > cog is a thin controller (characterized by `test_on_message.py`).
  2. `mod` mute/unmute/ban command bodies.
     > **Done** — `plugins/mod/logic.py`: `split_duration_reason`,
     > `ensure_future`, `resolve_ban_type`; commands are thin controllers.
  3. `welcome` `on_member_update` body.
     > **Done** — `plugins/welcome/logic.py`: `should_welcome` over plain
     > values (deterministic `monitor in gained` vs the old `set.pop()`).
  4. `frogs` capture/consume math; scheduler handlers (`on_frog_due`,
     `on_modlog_due`, `on_counter_expire`) split into pure S + thin C shim
     (the `(bot, payload)` plugin contract itself stays).
     > **Done (consume)** — `plugins/frogs/logic.py`: `exp_per_frog`,
     > `consume_total_exp`, `ensure_consume_amount` (spawn math was already
     > pure in `factory.py`). The scheduler handlers + capture view stay
     > controller-shaped by design (scheduling + discord side effects).
  5. Template formatters take plain values / `cazzubot.models` instead of
     `Member`.
- **Enforcement:** an AST-level pytest that walks the plugin tree and asserts
  service modules (`logic.py`/`factory.py`) never `import discord` — fails with
  a readable message naming the file — plus the boundary rule documented in
  `docs/PLUGINS.md`. Enforcement lands after the `experience` pilot proves the
  pattern.
  > **Done** — `tests/core/test_csr_boundary.py` (AST walk over
  > `logic.py`/`factory.py`/`db.py`; one carve-out: `from discord.ext import
  > commands` for the plain `BadArgument` exception). **Remainder** (tracked
  > in the test's allowlist): `plugins/levels/logic.py`,
  > `plugins/ranks/logic.py`, `plugins/frogs/factory.py` — presentation/
  > handler modules that still import the core `discord` package until their
  > extraction step. PLUGINS.md documents the rule.
- **Why:** pure-S is the unit-testable core (mirrors the unit-testing item
  below), cuts the fake-discord surface down to the controller slice, and
  keeps the LSP a collaborator — no `Any` discord internals in service code.

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

## LSP Hints for Data
Have the LSP do as much hinting as we can for data so development is as seamless and frictionless as possible. No trying to guess what an object has, the LSP should be able to trivially determine what it is.

This is especially important for information retrieved from the database. It should cast into some type that can be trivially understood.

## Have actual and proper unit testing
All we have is the smoke.py and functest.py. They are unmanagable as they are monoliths. We need someway to have unit tests more isolated and per-feature rather than a single script.

> **Done** — pytest 9 + pytest-asyncio added to the `dev` group with
> `[tool.pytest.ini_options]`; per-feature tests under `tests/` (core: db
> schema-guard, scheduler, settings, templates, timeparse, levels, boot/
> persistence; plugins so far: experience, ranks, frogs, poll, mod).
> Booted-bot fixtures in `tests/conftest.py`, typed
> subclass-without-super discord fakes in `tests/fakes.py` (file-scoped
> pyright directive for the strict-rule exceptions). Both monolith scripts
> were ported 1:1 into these files and deleted — `scripts/smoke.py` →
> `tests/core/test_boot.py`, `scripts/functest.py` → the per-feature files.
> The port surfaced one stale functest check ("verify rejects attachments"
> was a self-catching no-op: its own `AssertionError` was swallowed by its
> `except Exception`; attachments are schema-legal now) — the port pins
> current behavior instead. 42 tests, `uv run pytest` green, basedpyright
> clean on `tests/`. Coverage expansion (cog dispatch, views, checks per
> feature) continues alongside backlog #7.

> **Done** — all four nits resolved: `register_inktober` accepts
> `TextChannel`/`Thread`/`VoiceChannel`/`StageChannel`; `unmute`/`unban`/
> `rank_clean` send a `window_error` when `ctx.guild is None`; `story_write`
> documents why `ctx.message` exists on prefix invocation; the `content`/
> `MISSING` dance in `factory.py` collapsed into a shared `templates.send`
> helper (`cazzubot/templates.py`) that all 8 template call sites use —
> the webhook's `str`-only `content`/`embed`/`embeds` typing is bridged
> once inside the helper via `MISSING` normalization, so no per-site `cast`
> remains. basedpyright clean, `0 errors, 0 warnings`.

## Fix mod duration parsing (single-token footgun)
`split_duration_reason` (`plugins/mod/logic.py`) splits the raw argument on the
first space, so only **single-token** durations parse (`2h`, `tomorrow`,
`2026-05-01`). Natural phrasing like `mute @x 2 hours being bad` fails to
parse and silently becomes a mute/ban **without expiry** — no scheduler task,
no modlog expiry — so `ban @x 2 hours bad` is a permanent ban where a tempban
was meant. Found while writing the mod characterization tests (pinned by
`tests/plugins/mod/test_cog.py::test_split_duration_reason`). Fix options:
try progressively longer prefixes until `normalize_time_str` succeeds
(characterization test first, per the #7 loop), or restrict the command help
text to single-token durations.

## Welcome role-mode determinism (fixed during extraction)
The old `on_member_update` ROLE-mode check used `set.pop()` on the gained-role
set — order-dependent when several roles are gained in one update, so whether
the monitored role triggered a welcome was hash-order-dependent. The extracted
`plugins/welcome/logic.py::should_welcome` uses `monitor_rid in gained` —
same behavior for the single-role case, deterministic (and arguably more
correct) for multi-role. No action needed; recorded for context.
