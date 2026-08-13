# Done

Completed backlog items, archived from `docs/BACKLOG.md` on 2026-08-13.
Each entry keeps its original problem statement plus the **Done** note
recording how it was resolved (a few record a **Decided against** outcome
instead — reviewed and rejected, with the reasoning kept). Open items live
in `docs/BACKLOG.md`.

---

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

> **Done** — `Plugin.depends_on` + `select_plugins` (`cazzubot/plugin.py`)
> ship this: transitive closure over `depends_on`, unknown names/deps fail
> the boot with a clear message, dependencies load first (topological sort,
> ties by discovery order), and cycles are *not* an error — strongly-
> connected components (experience ↔ ranks) load together as a unit.
> `main.py -s [PLUGIN ...]` feeds the allowlist; bare `-s` keeps the
> `poll`/`dev` defaults. Declared: experience→(levels,ranks),
> levels→(ranks,), ranks→(experience,), frogs→(experience,),
> daily→(experience,frogs), quarterly→(frogs,).

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

> **Done** — the history is now the source of truth. `counter` is the
> registry (`id` PK + `mid`, no `count` column); every press is one
> `counter_event` row (`counter_id` fkey to `counter.id`, `uid`, `name`,
> `updated_at`, index on `(counter_id, updated_at)`), recent bakas = the
> distinct `uid`s whose latest press is inside the 2h window
> (`GROUP BY uid` over `MAX(updated_at)` desc), total = `COUNT(*)` over the
> history. Legacy pre-normalization presses were backfilled as anonymous
> rows (`uid`/`name` NULL, epoch timestamp `1970-01-01T00:00:00+00:00`) —
> one per old press — so totals carry over exactly
> (`scripts/migrate_counter_events.py` for an in-place SQLite conversion;
> the PG→SQLite migration emits the same shape
> (`scripts/migrate_pg_to_sqlite.py`), `verify_migration.py` checks it, and
> `scripts/migration/MAPPING.md` documents the mapping). `counter create`
> takes an optional `counter_id` to re-create a counter whose Discord
> message was deleted — the events (and count) carry over. The baka-
> specific presentation (button, footer text, `recent_bakas`) is unchanged
> by design.

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

## Port the CLI tooling to hikari REST (then drop discord.py)

> **Done** — the CLI runs on `hikari.RESTApp` (no gateway) and discord.py
> is fully removed from the environment. Live verbs (`export`/`diff`/
> `check`/`apply`/`restore`/`snapshot fetch`) go through
> `with_client`'s REST client (`acquire(token, "Bot")` — the default
> token type is BEARER); role reorders use hikari's `reposition_roles`,
> channel creates/edits/reorders go through hikari's own rate-limited
> request path with raw payload keys; `roles/parser.VALID_FLAGS` derives
> from hikari; the CSR allowlist is gone. Validated live against the
> sandbox guild: export/check/diff clean, apply cycles for create, rename,
> delete and reorder, and a channels rename — all reverted afterwards.
> `scripts/boot_check_migrated.py` was ported to the event-driven boot;
> the PG-migration scripts (`migrate_pg_to_sqlite.py`,
> `verify_migration.py`) remain asyncpg-based (install with
> `uv sync --group migration`).

## Chaotic schedules — the two families

Design riff on the cadence work (2026-08-09): schedule specs split into
an **absolute** family (`At` — the task runs AT a calendar time) and a
**relative** family (`In` — the task runs IN a duration), each with a
chaotic flavor:

- `At(time/weekday/day/months)` — the absolute declaration: daily,
  weekly (tuple of days allowed), day-of-month (1-31 or -31…-1 = the
  last day, tuples allowed), `months` eligibility (the quarterly
  rollover is `At(day=1, months=(1, 4, 7, 10), time="00:00")`); cron
  skip for months lacking a day; `next_run`/`previous_run`/`missed`
  are grid-anchored.
- `In(interval)` — the relative declaration: positive seconds or a
  duration string (`"2h"`, `"90m"` via `timeparse.parse_duration`);
  `next_run = now + interval`, sliding with each fire; `previous_run`/
  `missed` are relative.
- `AtChaotic(At)` — absolute + chaos: the run lands at the occurrence
  plus up to `jitter` (0..1) of the period, drifting forward within the
  window; `seed` for deterministic tests, `bounds()` RNG-free.
- `InChaotic(In)` — relative + chaos: `now + interval * (1 ± jitter)`.
- `previous_run`/`missed` are inherited per family; missed handling is
  per-handler anyway (row-based catch-up: fire-always + re-arm-last).
- `Scheduler.arm` was removed — handlers re-arm explicitly via
  `drop_tag` + `add` (arm's empty-payload/drop-tag shape only ever fit
  daily/quarterly; frogs add per-channel rows with payloads).
- (2) future pipeline schedule specs — `{"at": …}` / `{"in": …}` /
  `{"at_chaotic": …}` / `{"in_chaotic": …}` families.
- Not designed yet: window-anchored chaos — "daily at a random time
  between 12:00 and 18:00, re-rolled each day" (AtChaotic's forward
  drift is the first step; a two-sided window would follow).

> **Done (2026-08-09)** — the split landed in `cazzubot/scheduler.py`.
> Frogs spawn on the **pure chaotic timeline** via `InChaotic`:
> `on_frog_due` rolls the next spawn from the fire instant and
> schedules it *before* spawning (failure safety kept); the old
> despawn-anchored pre-roll and capture re-roll (`persist`-anchored,
> `update_run_at`) are gone, so frogs may overlap and capturing no
> longer speeds up the next spawn. `roll_future_frog`/`roll_fuzzy`
> deleted. `At`/`AtChaotic`/`In`/`InChaotic` replace the former
> `Cadence`/`CadenceChaotic` (which had folded both modes into one
> type); `Scheduler.arm` removed. Tests: `test_cadence.py`
> (validation, seeded determinism, bounds, both families) + the
> fire-instant spawn test.

## Generic scheduler — time/interval-triggered command chains (pipelines)

> **Decided against (2026-08-13)** — superseded by code-based scheduled
> flows. Single-guild, owner-operated bot: the weekly board flow is the
> only chain anyone would run, its only operator writes code, and admins
> won't compose functions through non-code — so the definitions table,
> `ctx.output` convention, `/pipeline` commands and `&&`/`|` DSL are a
> parallel execution substrate for one fixed workflow (overkill). The
> equivalent is a `weekly` scheduler tag (`At(weekday=(6,), time="00:00")`,
> mirroring `plugins/daily/__init__.py`) whose handler calls extracted
> service functions directly; abort-on-`UserInputError` and retry
> semantics already live in the scheduler (`retry: True`, `TaskPolicy`),
> so nothing below is lost except runtime-editable chains — which were
> explicitly unwanted. The board weekly flow stays backlogged under the
> board item in `docs/BACKLOG.md`. Revisit only if 3+ distinct automated
> flows ever appear.

Owner's goal: write a "command" that runs at intervals — a chain of
application commands (or functions marked public) piped together, e.g.:

    at the start of every sunday
    board scrape && board post | poll register && poll send

where `board post` outputs the image count and `poll register`'s pid is
auto-populated with it. Feasibility assessed (2026-08-09): very doable —
the central scheduler and offline command invocation already exist; the
real work is structured command output + a pipeline runner.

Design:

- **Structured command outputs** — the missing convention. Pipeable
  commands set `ctx.output = {...}` (e.g. `{"count": 20}`, `{"pid": 7}`)
  alongside their normal window feedback; only pipeable commands need it.
- **Pipeline runner** — executes steps sequentially against the real bot
  with a captured context (the same trick `tests/driver.py` /
  `invoke_command` use offline); a step raising `UserInputError` aborts
  the chain (that's the `&&`); otherwise the next step's params bind from
  the previous output (that's the `|`), e.g. `n: "$prev.count"`. Runs as
  its own task so the scheduler loop never blocks (pattern: poll modal
  attach wait).
- **Definitions** — JSON first: `{steps: [{command, args}, ...], channel,
  schedule}` (validated, testable); a shell-like `&&`/`|` DSL parser is a
  possible later nicety that compiles to the same JSON.
- **`pipelines` table + cadence** — name, schedule, definition, enabled;
  the schedule spec family (`At` — absolute calendar declarations — and
  `In` — relative durations — each with a `Chaotic` flavor; `next_run`/
  `previous_run`/`missed` — landed 2026-08-09); `/pipeline` admin
  commands (define/list/run <name> for dry-runs).
- **Semantics** — the definition carries the channel; pipelines run with
  owner privileges (only the owner defines them); abort-on-
  `UserInputError` is the failure rule (already the bot's error
  convention).
- Refactor the `daily` and `quarterly` plugins onto the same cadence
  helper (they hand-roll the midnight pattern today).
  > **Done** — `At(time="00:00")` in `cazzubot/scheduler.py`; both
  > plugins re-arm with it, and
  > `utils.arm_midnight_cadence` / `next_midnight` deleted. Tests in
  > `tests/core/test_cadence.py`. Follow-up (2026-08-09, design B):
  > `daily` is now **row-based** — the task row is the sole schedule.
  > `on_daily_due` resets then re-arms (arm-last, so a failed reset is
  > retried by the scheduler's 30s policy instead of silently no-oping),
  > and `on_load` arms only when no row exists — an overdue row fires
  > on boot through the scheduler's native catch-up, so the missed
  > reset runs late instead of being forced. `daily.last_daily` and the
  > `Cadence.missed` gate are gone. Quarterly followed suit
  > (2026-08-09): `At` grew a day-of-month family (`day` 1-31 +
  > optional `months` 1-12, cron-skip semantics, e.g. Feb 31), and
  > quarterly is now `At(day=1, months=(1, 4, 7, 10), time="00:00")`
  > — the season rollover *is* the schedule, so `quarterly.last_quarterly`
  > and the quarter-index gate are gone too: every fire freezes
  > (idempotent) and re-arms. `scripts/boot_check_migrated.py` now
  > asserts the armed row instead of a boot-time freeze. The declaration
  > surface is cron-flavored: `weekday` also accepts a tuple of days,
  > `day` accepts -31…-1 (the last day) or a tuple, and durations live
  > in the `In` family (`In(interval="2h")`). `Scheduler.arm` was
  > removed (handlers re-arm explicitly via `drop_tag` + `add`). Retry
  > is **explicit**: a task resolves by default when due (v1's contract —
  > the fired row is deleted whether the handler raised or not); a task
  > opts into guaranteed handling with the reserved payload key
  > `retry: True`, which keeps and re-arms the row per its tag's
  > `TaskPolicy` (backoff, attempt cap). modlog expiry, daily, and
  > quarterly opt in; frogs stay fire-and-forget.
- First consumer: the board weekly flow — `board scrape` →
  `board post` (outputs the image count) → `poll register` (outputs pid)
  → `poll item auto_populate` (`pid` from output, `n` from count) →
  `poll send`, Sunday 00:00 UTC.
- Overlaps with `cazzubot/scheduler.py` (tags, payloads, retry, re-arm on
  boot) — potential refactor there as well.

## One switch for prod vs sandbox guild

Today `GUILD_ID` in `.env` is hand-edited to point the bot at production
(`293796316193095690`) or the sandbox dev guild (`408801760581386245`).
Want a trivial, unified way to pick the guild — e.g. a `GUILD=prod|sandbox`
(dev) selector in `.env` mapping to the two known ids, or having `-p`
imply the production guild (with the default dev run implying the sandbox
guild) — that both the bot (`main.py`) and the
CLI (`cazzubot-cli`, which already honors a shell `GUILD_ID=…` override)
share. Keep `GUILD_ID` working as the escape hatch for any other guild.

> **Done** — `--bot`/`--guild` side flags replace `-p/--production` in both
> `main.py` and `cazzubot-cli`. Each accepts `production|p|develop|d`
> (default `develop`): `--bot` picks the token (`TOKEN` vs `TOKEN_DEV`),
> `--guild` picks the guild. The guild ids moved out of the repo into
> `.env` as `GUILD_ID_PROD`/`GUILD_ID_DEV` (gitignored; required when that
> side is selected) — `GUILD_ID` env is no longer read, and there is no
> hardcoded-id escape hatch. `Config.load(bot=…, guild=…)` stores the
> chosen side as `Config.guild_kind` (the canonical "which guild am I on"
> reference). Terminology: the second guild is now the **development**
> guild; "sandbox" means only the `-s` plugin-allowlist mode. `scripts/
> probe_channels.py` follows the new flags; the legacy PG migration
> scripts still read `GUILD_ID` env directly (follow-up).
