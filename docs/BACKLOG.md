# Backlog

Deferred work, parked by request ("we will work on it later when I request it").
Pick these up when the owner asks; each item links to the discussion that
motivated it.

## Schema verification and row casting for monolithic pluigins
I think currently the code only looks for a db module for plugins and uses that to verify the schema and to cast rows into the dataclass. If a module isn't structured as CSR, this feature might not function.

If a plugin isn't CSR, it should hopefully still try to look at __init__.py for defined dataclass and like for schema verificaiton and row casting.

> **Done** — neither feature depends on a `db.py` module, so monolithic
> plugins already get both. Schema verification is driven by the
> `Plugin.schema` attribute (`cazzubot/plugin.py`), collected from every
> plugin and drift-checked at boot by `CazzuBot.setup_hook` +
> `Database.verify_schema` (`cazzubot/bot.py`, `cazzubot/db.py`); CSR
> plugins writing `schema = db.SCHEMA` in `__init__.py` is just an import,
> and a monolithic `__init__.py` can inline the same DDL list. Row casting
> is a call-site utility (`Database.fetch_model`/`fetch_models`, `row_to`/
> `rows_to` in `cazzubot/db.py`) that takes the model type explicitly — a
> monolithic `__init__.py` can define a `@dataclass` and call it directly.
> No plugin today exercises it monolithically only because the monoliths
> (`daily`, `dev`, `fun`, `levels`, `quarterly`, `welcome`) own no tables —
> they use settings, files, or other plugins' `db` modules.

## Plugin dependency policy — `depends_on`

Add `depends_on: list[str]` to the `Plugin` base (`cazzubot/plugin.py`). The
loader (`cazzubot/bot.py`) should:

- validate declared deps exist and load them first,
- fail fast with a clear error (not a confusing `ModuleNotFoundError`),
- respect the sandbox allowlist,
- detect dependency cycles.

## `bot.get_plugin(name)` + optional-dependency degrade

Public accessor for loaded plugins (today callers reach into
`bot._plugin_by_name`, e.g. `plugins/dev/__init__.py`). Plus a degrade pattern
for optional dependencies: if a dependency is unloaded/hotswapped, dependents
skip their call instead of crashing.

## Core event bus — `bot.events`

`emit`/`on`/`off` for bot-specific events (`member_leveled_up`,
`frog_captured`, …) so producers never know their consumers. Design decision
already made: the bus lives in **core** (`cazzubot/events.py`) — a generic
capability, not feature logic. Caveat to respect: events are less traceable
than direct calls and ordering isn't guaranteed — reach for them only when the
producer shouldn't know the consumer exists.

## Event-bus consumer demo

One real consumer (e.g. a "level-up milestone" channel) to validate the bus
design before wider adoption.

## Levels coupling cleanup

Move `handle_level_up`/`formatter` from `plugins/levels/cog.py` to
`plugins/levels/logic.py` (mirroring `plugins/ranks/logic.py`) so the
`experience` plugin imports service→service, not cog→cog. Prerequisite for the plugin-dependency-policy item
to be coherent.

> **Done** — `MESSAGE_KEY`/`formatter`/`handle_level_up` live in
> `plugins/levels/logic.py`; the cog is config-only and re-imports them.
> `experience` and `scripts/functest.py` import from `plugins.levels.logic`,
> so no plugin reaches into another plugin's cog (mirrors `ranks/logic.py`).

## Register persistent poll button view on boot

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

## Enforce Controller → Service → Repository within plugins

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
     event-bus subscriber — see the core event bus item).
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
  > `logic.py`/`factory.py`/`db.py`; no carve-outs left — the
  > `commands.BadArgument` exception import is gone too, replaced by
  > `cazzubot.errors.UserInputError`). `plugins/frogs/factory.py` stays
  > controller-shaped by design (spawn/capture are discord side effects)
  > and is the one permanent allowlist entry.
  > PLUGINS.md documents the rule.
- **Why:** pure-S is the unit-testable core (mirrors the unit-testing item
  below), cuts the fake-discord surface down to the controller slice, and
  keeps the LSP a collaborator — no `Any` discord internals in service code.

---

Context: these came out of the architecture discussion about three-tier
layering, plugin-to-plugin coupling (direct import vs data contract vs event
bus), and the levels kernel naming collision (`cazzubot/levels.py` vs
`plugins/levels/`). See docs/ARCHITECTURE.md and docs/PLUGINS.md. The poll-view re-registration item was
parked during the reaction→button conversion (2026) to keep that change
focused.

---

## Counter DB rework
A single reaction on the counter should store the following:

mid,user,timestamp

Now we have a history of people who have pressed the button. From this, we can simplify the calls. The recent bakas can be a database call, grouped by user, summed. From this, we can get the most recent bakas.

We can also get the total count for the counter just by a sum call on the mid.

> **Partly done** — `counter_baka` (mid, uid, name, updated_at) already IS
> the per-press history, and the baka button derives "recent bakas" from it
> (`SELECT name ... ORDER BY updated_at DESC`). Still open: the total count
> is still maintained as `counter.count` (`UPDATE counter SET count = count + 1`)
> instead of a `SUM` over the history — the "count by sum on mid" half of
> the item remains.

## Fix mod duration parsing (single-token footgun)
> **Done** — `split_duration_reason` takes the first parseable leading
> prefix, extended greedily over duration-like tokens, so multi-word
> phrasing (`ban @x 2 hours bad`) no longer silently becomes a no-expiry
> ban and compounds fold in (`2 hours 5 minutes`, `2h 5m`, `tomorrow 5pm`).
> Characterized in `tests/plugins/mod/test_cog.py::test_split_duration_reason`.

`split_duration_reason` (`plugins/mod/logic.py`) splits the raw argument on the
first space, so only **single-token** durations parse (`2h`, `tomorrow`,
`2026-05-01`). Natural phrasing like `mute @x 2 hours being bad` fails to
parse and silently becomes a mute/ban **without expiry** — no scheduler task,
no modlog expiry — so `ban @x 2 hours bad` is a permanent ban where a tempban
was meant. Found while writing the mod characterization tests (pinned by
`tests/plugins/mod/test_cog.py::test_split_duration_reason`). Fix options:
try progressively longer prefixes until `normalize_time_str` succeeds
(characterization test first, per the CSR test-then-extract loop), or restrict the command help
text to single-token durations.

## Levels/ranks presentation split
> **Done** — `handle_level_up`/`handle_ranks` split into pure decisions
> (`levels.logic.decide_level_up`, `ranks.logic.plan_rank_changes` over
> plain role ids) + thin presenters (`plugins/levels/presenter.py`,
> `plugins/ranks/presenter.py`) holding the side effects. The experience
> controller calls the presenters; `test_csr_boundary.py` allowlist only
> keeps `plugins/frogs/factory.py`.

`handle_level_up` (`plugins/levels/logic.py`) and
`handle_ranks`/`_determine_rank_changes` (`plugins/ranks/logic.py`) still take
`bot` + `discord.Message` and perform the presentation side effects — sending
the level-up/rank-up message and mutating roles (`add_roles`/`remove_roles`).
They are called from the experience controller (`_award_exp`), so the work is:
keep the decisions in `logic.py` (`_determine_rank_changes` is ~90% pure
already — it only touches `guild.get_role`/`member.roles` at the edges;
`should_notify(level, quiet_ids)` would be pure) and move the side effects
into a thin presenter — or an event-bus subscriber once the core event bus
exists. Safety net already in place: `tests/plugins/ranks/test_presentation.py`.
Allowlisted in `tests/core/test_csr_boundary.py`.

## Template formatters take `Member`
> **Done** — formatters now take `cazzubot.models.MemberSnapshot` (plain
> values: id/display_name/mention/avatar_url), built at the controller edge
> with `utils.member_snapshot`. `templates.verify(..., member=)` call sites
> snapshot `ctx.author`/`interaction.user`; ranks formatter takes role
> *mention strings*, so role resolution happens in the presenter.

`levels.logic.formatter`, `ranks.logic.formatter` and `frogs.factory.formatter`
read `member.display_avatar.url` / `display_name` / `mention` / `id` —
stateful discord objects in the service layer. Change them to take plain
values (or a `cazzubot.models` dataclass); the `templates.verify(..., member=)`
call sites (`welcome_set_message`, `frog_set_message`) change with them. This
is the last piece of the CSR item's "template formatters" extraction step.

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

> **Done** — all four nits resolved: `register_inktober` accepts
> `TextChannel`/`Thread`/`VoiceChannel`/`StageChannel`; `unmute`/`unban`/
> `rank_clean` send a `window_error` when `ctx.guild is None`; `story_write`
> documents why `ctx.message` exists on prefix invocation; the `content`/
> `MISSING` dance in `factory.py` collapsed into a shared `templates.send`
> helper (`cazzubot/templates.py`) that all 8 template call sites use —
> the webhook's `str`-only `content`/`embed`/`embeds` typing is bridged
> once inside the helper via `MISSING` normalization, so no per-site `cast`
> remains. basedpyright clean, `0 errors, 0 warnings`.

## LSP Hints for Data
Have the LSP do as much hinting as we can for data so development is as seamless and frictionless as possible. No trying to guess what an object has, the LSP should be able to trivially determine what it is.

This is especially important for information retrieved from the database. It should cast into some type that can be trivially understood.

> **Done** — `Database.fetch_model` / `fetch_models` are generic
> (`type[_T] -> _T | None` / `list[_T]`) and build typed dataclass models
> from rows; every repository layer now uses them (`MemberExp`, `RankThreshold`,
> `Spawn`, `Task`, `Poll`, `PollResult`, `PollRow`, ...). The schema-drift
> tests (`tests/core/test_db.py`, typed-row checks in the plugin db tests)
> pin the column names so renames fail loudly instead of silently returning
> wrong-typed rows. `row_to`/`rows_to` in `cazzubot/db.py` are the single
> mapping point.

## Have actual and proper unit testing
All we have is the smoke.py and functest.py. They are unmanagable as they are monoliths. We need someway to have unit tests more isolated and per-feature rather than a single script.

> **Done** — pytest 9 + pytest-asyncio added to the `dev` group with
> `[tool.pytest.ini_options]`; per-feature tests under `tests/` — core
> (schema-guard, scheduler, settings, templates, timeparse, levels, boot/
> persistence, window, CSR boundary) plus every plugin (experience, levels,
> ranks, frogs, poll, mod, welcome, counter, daily, quarterly, dev, fun):
> 122 tests covering commands, views (poll modal, confirm, top pager, frog
> catch, baka), scheduler due-handlers, reset loops, owner gates and the
> level/rank presentation layer. Booted-bot fixtures in `tests/conftest.py`,
> typed subclass-without-super discord fakes in `tests/fakes.py` (file-scoped
> pyright directive for the strict-rule exceptions). Both monolith scripts
> were ported 1:1 into these files and deleted — `scripts/smoke.py` →
> `tests/core/test_boot.py`, `scripts/functest.py` → the per-feature files.
> The port surfaced one stale functest check ("verify rejects attachments"
> was a self-catching no-op: its own `AssertionError` was swallowed by its
> `except Exception`; attachments are schema-legal now) — the port pins
> current behavior instead. `uv run pytest` green (122 passed, 0 warnings),
> basedpyright clean on `tests/`.

## Welcome role-mode determinism
The old `on_member_update` ROLE-mode check used `set.pop()` on the gained-role
set — order-dependent when several roles are gained in one update, so whether
the monitored role triggered a welcome was hash-order-dependent. The extracted
`plugins/welcome/logic.py::should_welcome` uses `monitor_rid in gained` —
same behavior for the single-role case, deterministic (and arguably more
correct) for multi-role.

> **Done** — resolved by the extraction; recorded for context.

## Core asset management (design in docs/ASSETS.md)

Full design written up in `docs/ASSETS.md` from the gamification planning
discussion — parked here for later review and potential implementation. The
short version: a three-layer system — plugin-declared definitions (static in
git / dynamic via admin upload), a content-addressed registry table (catalog
of records, namespaced keys), and Discord-CDN delivery (sha256-diffed sync to
a private asset channel, URL-only so templates/embeds stay untouched).
Prerequisite (also designed there): the frogs catalog rework — species rows +
inventory + recipes replace the current column-per-type model
(`member_frog.normal/frozen`, `FrogTypeEnum`), with effects via a
string-key → handler registry and dishes as crafted species.

## Declarative channel management (channels.manifest)

> **Done** — implemented and validated against both guilds (sandbox full
> create/delete/rename/reorder/restore cycles; production scoped
> renames+moves in "Activities and below", then reverted). Engine in
> `cazzubot/channels/`, CLI domain `channels`, boot drift-check plugin in
> `plugins/channels/`; see docs/PLUGINS.md → channels.

A roles-style declarative system for the guild's channels: a
`channels.manifest` line format — `[Category]` headers map to Discord's
*native* grouping (categories — the earlier claim that Discord has no
native way to group channels was wrong), one channel per line, verbatim
names like the role manifest — with a `channels` domain in the CLI
(`export` / `diff` / `apply` / `check` / `restore`, plus a
`--scope-below <Category>` flag to manage only the bottom part of a busy
guild), mirroring the roles feature. The manifest declares what the
Overview tab covers **except the channel topic**: name, type
(text/announcement/voice/forum/stage), category, position, slowmode,
nsfw, and the voice fields (bitrate, user limit, region, video quality —
Discord removed 720p, so auto/1080 only).
Permission overwrites are deliberately out of scope for now (mirroring
the roles feature's role-level-perms decision). Still open: the channel
topic, permission overwrites, and how the bot's channel-dependent
plugins (welcome channel, etc.) declare their channel requirements.
(Noted during validation: category size cap of 50 channels, and
announcement/stage channel creation needs the NEWS/COMMUNITY guild
features.)

## Run the bot via a [project.scripts] entry

`main.py` is run as `uv run python main.py [-d|-p|-s]`. Add a
console-script entry (e.g. `cazzubot = "…:main"`) so the bot runs as
`uv run cazzubot -d`, consistent with the `cazzubot-cli` entry added for
the role CLI. Requires moving main()'s logic into the package (e.g.
`cazzubot/__main__.py` or a small run module) so it is importable as a
script target; keep the existing `python main.py` path working.

## Port the CLI tooling to hikari REST (then drop discord.py)

The roles/channels/snapshot CLI (`cazzubot/cli/*`, `cazzubot/roles/*`,
`cazzubot/channels/*`) still boots a throwaway discord.py client. When the
owner requests it:

- rewrite the live verbs (`export`, `diff`, `check`, `apply`, `restore`,
  `snapshot fetch`) against `hikari.RESTApp`/`RESTClient` (no gateway
  needed) — the engine layers (`parser`, `plan`, `snapshot_channels`)
  are already framework-agnostic (`channels.executor._kind_of` resolves
  both frameworks; `roles/parser.VALID_FLAGS` derives from hikari)
- remove `discord.py` from the `cli` dependency group and from
  `tool.uv.default-groups` (pyproject.toml comment marks the spot)
- delete the last discord imports in `cazzubot/cli/core.py` etc. and drop
  the CLI allowlist in `tests/core/test_csr_boundary.py`
- port `scripts/boot_check_migrated.py` / `verify_migration.py` /
  `migrate_pg_to_sqlite.py` when touched (they still reference
  `setup_hook`/`wait_until_ready`)
