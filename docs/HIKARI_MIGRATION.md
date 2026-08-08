# Hikari migration — the seam map

Goal: swap `discord.py` → `hikari` with behavior intact. **Status: done as
of 022ba52** — the bot runs on hikari 2.5 + hikari-lightbulb 3.2 (slash-only,
guild-scoped), all 14 plugins are ported, and the suite is green (260
passed). The remaining discord.py consumers are the CLI tooling
(roles/channels/snapshot) and the legacy scripts, tracked in docs/BACKLOG.md
(the "port CLI to hikari REST" follow-up). This doc is the map that guided
the port; everything marked **pure** survived untouched, everything marked
**framework-bound** was rewritten as described.

## Current state of the seams

### Pure — survives the swap untouched

| Module | What it owns |
|---|---|
| `cazzubot/config.py` `db.py` `settings.py` `scheduler.py` `plugin.py` `timeparse.py` `levels.py` `leaderboard.py` `models.py` `errors.py` | No discord imports. `models.MemberSnapshot` is the plain-value member type. `errors.UserInputError` is the framework-agnostic validation exception. |
| `cazzubot/window.py` | Already protocol-based: `CommandWindow` flushes through a `Sendable` (`send(content, ephemeral=)`) — `fakes`/`ctx`/interactions all satisfy it. No change. |
| `cazzubot/templates.py` — schemas, `verify`, `prepare` | `verify` raises `UserInputError`; `prepare` returns **plain JSON** (`content`, embed dict, embeds list) — no discord objects. |
| `plugins/*/logic.py`, `plugins/*/db.py` | Pure (enforced by `tests/core/test_csr_boundary.py`). `levels.logic` (`decide_level_up`, formatter) and `ranks.logic` (`plan_rank_changes`, `rank_difference`, `is_ranked_up(db, ...)`, formatter) take plain values + `MemberSnapshot`. |
| The roles/channels CLI cores | `roles/parser|plan`, `channels/parser|plan`, and the `*.executor` decision layers are pure; only the fetch/export/CLI glue is bound (see below). |
| 150+ core + service tests | No discord imports; run unchanged. |

### Framework-bound — the actual rewrite surface

| Module | Becomes |
|---|---|
| `main.py`, `cazzubot/bot.py` | hikari gateway client + command framework loader. `CazzuBot`'s service ownership (db/settings/scheduler/plugins), two-phase plugin load and `verify_schema` boot guard carry over verbatim; only the `commands.Bot` base, intents, `tree.sync`, cog add/remove, `on_command_error` translation (keep the `UserInputError` unwrap) change. |
| `plugins/*/cog.py` (counter, daily, dev, experience, frogs, fun, mod, poll, quarterly, ranks, welcome) | Command definitions move to the chosen framework (tanjun / lightbulb / raw). `hybrid_command` has **no hikari equivalent** — tanjun's shared callback (`@as_slash_command` + `@as_message_command` on one function) is the closest. Cog-raised `commands.BadArgument` → the framework's user-facing error type. |
| `plugins/levels/presenter.py`, `plugins/ranks/presenter.py` | The model for presentation code: call pure logic, then discord side effects. Only the side effects (reaction, `add_roles`, sends) change. |
| `plugins/frogs/factory.py` | Stays controller-shaped by design (spawn handler + capture view) — the one permanent `test_csr_boundary.py` carve-out. `FrogCatchView` becomes a component event handler. |
| `cazzubot/utils.py` — `prepare_embed`, `find_user`, `ConfirmView`, `author_confirm`, `member_snapshot` | `member_snapshot` is the pattern: discord at the edge, plain values everywhere else. `ConfirmView`'s `(author_id) → bool|None` contract ports directly to component-event handlers. |
| `cazzubot/templates.py` — `embed_from_raw`, `send` | The single embed-conversion seam: reimplement `embed_from_raw` for `hikari.Embed`; `send` keeps forwarding `content/embed/embeds` to the target. |
| CLI tooling | `cazzubot/cli/core.py` boots a throwaway `discord.Client`; `roles/export.py` + `channels/export.py` fetch guild state; `cli/roles.py|channels.py|snapshot.py` glue. Decision needed: port to hikari REST (kills discord.py entirely) or keep as the one discord.py consumer. |
| `scripts/probe_*.py` | dev probes; port when touched. |

### Error type mapping (used today → hikari)

| discord.py | hikari |
|---|---|
| `discord.NotFound` | `hikari.NotFoundError` |
| `discord.Forbidden` | `hikari.ForbiddenError` |
| `discord.HTTPException` (bot.py `on_ready`) | `hikari.HikariError` base / `hikari.InternalServerError` |
| `discord.DiscordServerError` (frogs spawn) | `hikari.InternalServerError` |
| `commands.BadArgument` (cog edge only) | framework error type (tanjun: `tanjun.BadMessageArgumentError`-style / lightbulb equivalent) |
| `cazzubot.errors.UserInputError` (service/core) | unchanged — translate at the edge, as `bot.py` does today |

## Fake-surface freeze (`tests/fakes.py` is the contract)

The suite's de facto interface. Port the fakes against **this list**, not
against hikari's API. `discord.py` models are loose (assign `self.id`)
and fakeable by subclass-without-`super().__init__`; hikari models are
immutable `attrs` classes with `__slots__` — that trick dies. Rebuild the
fakes as standalone classes implementing the same surface (or `hikari.impl`
mutable copies where cheap).

Stable semantics (port 1:1 — the rewrite spec):

| Surface | discord.py today | hikari mapping |
|---|---|---|
| member identity | `id`, `name`, `display_name`, `mention`, `display_avatar.url` | `Member.id/display_name/mention/avatar_url` (no `.url` indirection) |
| member roles | `member.roles` (list of Role) | `member.role_ids` + `cache.get_role` — presenters already plan by **ids** (`plan_rank_changes(member_role_ids=...)`) |
| member perms | `guild_permissions` | `member.permissions` (guild context) / `Permissions` bitflags (`Permissions(administrator=True)` → `hikari.Permissions(hikari.Permissions.ADMINISTRATOR)`) |
| member mutation | `add_roles`/`remove_roles`/`kick`/`ban` (recorders in fakes) | `rest.add_role_to_member` / `remove_role_from_member` / `kick_member` / `ban_member` — recorders become rest-client spies |
| guild lookup | `guild.get_member/get_role/get_channel`, `fetch_member` | `cache.get_member/get_role/get_guild_channel`; `rest.fetch_member` |
| channel send | `channel.send(...)`, `history`, `fetch_message`, `edit`, `typing()` | `channel.send` (via `MessageCreateEvent` target), `rest.fetch_messages/fetch_message/edit_channel`; typing: `rest.trigger_typing` (the ctx manager is a discord-ism — drop) |
| message | `add_reaction`, `delete`, `edit` | `rest.add_reaction`, `rest.delete_message`, `rest.edit_message` |
| interaction | `response.send_message/edit_message/defer/send_modal`, `followup.send`, `original_response` | `interaction.create_initial_response/edit_initial_response/defer`, `interaction.execute_webhook` (followup); **modal support must be verified** — `plugins/poll` uses `PollModal` (`plugins/poll/cog.py:191`) |
| send target | `ctx.send/reply` + `window.Sendable` protocol | tanjun `Context.respond` / slash `respond(ephemeral=True)` — the `Sendable` protocol (`cazzubot/window.py`) already abstracts this; keep it |
| bot cache internals | `bot._connection._guilds[gid]` (`seed_guild` in fakes), `bot._resolve_channel` | hikari's `MemoryCache` is publicly constructible and seedable — easier than today, but the fixture (`tests/conftest.py` booted-bot) must be rewritten to build a real hikari client + cache |
| views / buttons | `discord.ui.View` with `wait()` (ConfirmView, TopView pager, FrogCatchView) | hikari components are builders (`hikari.impl.ButtonBuilder` + `MessageActionRowBuilder`); the `view.wait()` state machine becomes an `InteractionCreateEvent` handler — the biggest structural change in the controller layer |

Framework mechanics (drop or map during the port, by rule): exact kwargs
dicts recorded in fakes' `sent`, `ctx.reply` vs `ctx.send` distinction,
`discord.NotFound` identity, `commands.BadArgument` message strings.

## Decisions to lock before starting

1. **Command framework** — tanjun (hikari-official, shared slash+message
   callbacks ≈ current hybrids) vs lightbulb (cog-like) vs raw hikari.
2. **Modal support** — poll plugin depends on it; verify hikari's modal
   status (historically absent; merged later) before committing.
3. **CLI scope** — port the roles/channels/snapshot tooling to hikari REST
   in the same sweep (discord.py fully dies), or keep it as the last
   discord.py consumer temporarily.
4. **Prefix commands** — keep them (message-command framework) or drop to
   slash-only; affects tanjun wiring and `main.py` `-d`/`-p` prefixes.

## Port order (recommended)

1. `tests/fakes.py` + `tests/conftest.py` rebuild (the freeze list above is
   the spec) — get the suite green against hikari fakes while the bot is
   still discord.py? No — fakes import the framework's model classes, so
   they can't be dual. Instead: swap the framework first, then port fakes
   against the freeze list.
2. `cazzubot/bot.py` + `main.py` + command framework wiring.
3. Cog-by-cog: definitions → framework, side effects → presenters already
   exist, `UserInputError` unwrap → framework error handler.
4. `templates.embed_from_raw` + `utils.member_snapshot` + `window` send
   targets.
5. Views → component event handlers (Confirm, TopView, FrogCatch, poll).
6. CLI + scripts.
7. Drop `discord.py` from `pyproject.toml`; delete the now-dead fakes;
   tighten `test_csr_boundary.py` to also walk `tests/` (fakes must not
   import discord).
