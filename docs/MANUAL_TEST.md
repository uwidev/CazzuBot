# Manual test checklist — hikari rewrite (`rewrite-hikari`)

Live acceptance pass for the discord.py → hikari 2.5 + lightbulb 3.2
migration. The offline unit suite covers the logic layers; this list targets
what fakes cannot: the real gateway, live components/modals, permissions,
rate limits, restart behavior.

## Automated coverage (offline interaction driver)

Since the rewrite, most interaction flows are covered **offline** by the
driver in `tests/integration/` — no Discord needed, runs with `uv run pytest`:

- `tests/driver.py` — `run_slash` / `press_button` / `submit_modal` feed
  synthetic gateway interactions through hikari's own deserializer + event
  manager, so the real routing runs: raw `InteractionCreateEvent` listeners,
  lightbulb menu/modal lookup by `custom_id`, the command pipeline (option
  solving, checks, error handler), and the interaction-response lifecycle
  (single initial response within the 3s budget; webhook edits/deletes must
  be acked and address a real message — the 404/stall bug classes from the
  manual pass fail loudly instead). The `full_bot` fixture boots the real
  bot with every plugin against a temp DB.
- Covered scenarios: counter create + baka press + restart persistence
  (H1/H2), author-confirm menus incl. wrong-user rejection (C4/D3), frog
  spawn + catch + stale button (D4), poll vote modal + submit (F2/F3), the
  debug gate (B2), UserInputError translation (L1), `exp top` paging (C3),
  and the window reporting flow.
- What stays manual/live: real gateway events, rate limits, Discord's own
  payload validation, and two-real-user races.

See `docs/TESTING.md` for the full layered-testing strategy, the driver
mechanics, and the general automation boundaries.

**No formal bug reports.** If something is wrong, paste the error / write
whatever below the test item — raw, no template.

## Test environment

- **Never** mutate the production guild `293796316193095690` (Club Cirno).
- All mutating tests run against the **development guild
  `408801760581386245`** (`CazzuBot Dev`) with the dev token.
- CLI tests: point `--file` at a temp manifest so the production
  `roles.manifest` / `channels.manifest` and `data/roles_export.json` are
  never clobbered.
- Keep `log/discord.log` from every session — first place to look when
  something misbehaves.
- Use two accounts where noted (frog catch race, debug gate, mod checks).

## Setup

1. `uv sync` on the `rewrite-hikari` branch.
1. Boot the bot: `uv run python main.py -d`.
1. Confirm the slash tree registered in the development guild (B1).

______________________________________________________________________

## A. Boot & lifecycle

- [x] A1. `-d` boots clean: db connects, schema verify passes, all plugins
  load, no errors/warnings in `log/discord.log`.

- [x] A2. `-d -s` sandbox mode: only the default sandbox plugins load,
  no crash; `-d -s <plugin>` loads that plugin + its dependencies.
  **Open question:** the allowlist is `{"poll", "board", "dev"}` but no
  `plugins/board` exists — confirm this is intended (possible leftover).

- [x] A3. `-p` production mode boots with the prod token (read-only check).

- [x] A4. Schema drift: add a junk column to a table, reboot → clean refusal
  with the mismatch report, exit 1 (then revert the drift).

- [x] A5. Mutate a development-guild role/channel, reboot → roles/channels drift
  warning appears **after the guild dump lands** (new
  `GuildAvailable`-gated logic — timing-sensitive).

  ```
  After creating a new channel and role:
  [2026-08-08 16:38:50] [INFO    ] plugins.channels: channels manifest ok (1 unmanaged strays)
  [2026-08-08 16:38:51] [INFO    ] plugins.roles: roles manifest ok (1 unmanaged strays)

  The program notes that it's unmanaged? What are strays? I was under the impression that if there is a channel/role that exists in the manifest but not on remote (the guild), then it would be interpreted as a deletion.

  ...

  After some investigation, it seems seems their deletion would only occur with the deletion flag. I assume strays was put in place to state that they do not exist in manifest and are unmanaged as you stated. I'm not too sure how this unmanaged entity would interact during reorders.
  ```

- [x] A6. Graceful shutdown (Ctrl-C / `shutdown.sh`): scheduler stops,
  plugins unload, db closes, no "task destroyed" noise.

- [x] A7. Restart while a pending `tasks` row exists (frog spawn / counter /
  mute expiry) → no duplicate scheduling, due tasks still fire.

  ```
  Tried with baka button. A message sent by the bot on button press "This is not a baka counter anymore."

  For frogs, not too sure how I would test this, but I registered a frog spawn in #counting and it spawned. Restarted the bot and waited for the next frog to spawn. It spawned.
  ```

## B. Command registration

- [x] B1. Full slash tree present: groups `exp` (+`quiet`), `frog`, `rank`,
  `level`, `mod` (+`set`), `poll`, `welcome`, `counter`, `story`,
  `calc`, `plugin`; standalone commands (`ping`, `info`, `noot`, `echo`,
  `hashiresoriyo`, `register_inktober`, `scrape_inktober`, `owner`,
  `archive_emojis`, `scrape`); correct names/descriptions/option types.

  ```
  I do not see `/mod set` commands.
  ```

- [~] B2. Debug gate (`-d`): a non-owner/non-debug member is blocked with no
  error spam; the owner runs everything.

  ```
  There's way too much clutter from sqlite to see anything.
  ```

## C. experience / levels / ranks (cross-plugin flow)

- [x] C1. Message exp: send messages (~1/min to respect the cooldown),
  confirm `exp card` progress; cross a level threshold → level-up
  message with template, **rank role granted, rank-up message sent**.

- [x] C2. `exp quiet add/list/del` on a development-guild channel → level-ups
  suppressed there only.

- [!] C3. `exp top` paging (next/prev buttons), 30 s timeout → buttons
  removed cleanly; `exp lifetime`.

  ```
  Buttons do not do anything. "didn't respond in time".
  ```

- [!] C4. `exp resync` → Yes/No confirm view, window acks early, long UPDATE
  runs, ✓ synced.

  After confirming, bot hangs and does not respond to application, did not respond in time. I at least see follow up messages stating that it was synced. I think optimally we want better UX here. Will think of a proper flow later. Backlog this.

- [ ] C5. `level set/demo/raw` with a broken JSON template → jsonschema error
  surfaces as a user-facing window, not a silent failure.

  ```
  Demo failed.

  Traceback (most recent call last):
  ```

  File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/lightbulb/commands/execution.py", line 247, in \_run
  await getattr(self.\_context.command, self.\_context.command_data.invoke_method)(\*command_invoke_args)
  File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/linkd/solver.py", line 440, in \_\_call
  return await utils.maybe_await(self.\_func(self.\_self, \*args, \*\*new_kwargs))
  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/linkd/utils.py", line 101, in maybe_await
  return await item
  ^^^^^^^^^^
  File "/mnt/hdd/proj/high/in/CazzuBot/plugins/levels/extension.py", line 78, in invoke
  await templates.send(ctx, msg_json)
  File "/mnt/hdd/proj/high/in/CazzuBot/cazzubot/templates.py", line 199, in send
  return await destination.send(
  ^^^^^^^^^^^^^^^^
  AttributeError: 'Context' object has no attribute 'send'

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/lightbulb/client.py", line 1118, in \_execute_command_context
await pipeline.\_run()
File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/lightbulb/commands/execution.py", line 269, in \_run
raise exceptions.ExecutionPipelineFailedException(
...\<4 lines>...
)
lightbulb.exceptions.ExecutionPipelineFailedException: execution of command 'level demo' failed

## D. frogs

- [x] D1. `frog register`, wait a spawn cycle (interval ± fuzzy) → spawn
  message with catch menu in the right channel.

- [~] D2. Catch race: two accounts click the menu — exactly one wins.

  Can't test this with my setup.

- [!] D3. `frog profile` shows the frog; `frog consume` → Yes/No confirm →
  exp awarded (10/3 ratio); `frog lifetime`, `frog demo`, `frog raw`,
  `frog enabled` on/off.

  ```
  Profile shows, lifetime shows, raw shows, enable/disable works.

  Consumption does not work. Stalls on confirmation, didn't respond in time.

  [2026-08-08 17:17:46] [ERROR   ] hikari.event_manager: an exception occurred handling an event (ComponentInteractionCreateEvent)
  ```

Traceback (most recent call last):
File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/lightbulb/client.py", line 1220, in handle_interaction
await self.handle_interaction_create(event.interaction)
File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/lightbulb/client.py", line 1185, in handle_interaction_create
await self.handle_component_interaction(interaction, initial_response_sent_event)
File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/lightbulb/client.py", line 1160, in handle_component_interaction
await menu.on_interaction(interaction, initial_response_sent)
File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/lightbulb/components/menus.py", line 665, in on_interaction
await callback(context)
File "/mnt/hdd/proj/high/in/CazzuBot/cazzubot/utils.py", line 194, in \_yes
await self.\_finish(mctx, True)
File "/mnt/hdd/proj/high/in/CazzuBot/cazzubot/utils.py", line 190, in \_finish
await mctx.edit_response(mctx.interaction.id, component=None)
File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/lightbulb/context.py", line 230, in edit_response
return await self.interaction.edit_message(
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
...\<11 lines>...
)
^
File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/hikari/webhooks.py", line 424, in edit_message
return await self.app.rest.edit_webhook_message(
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
...\<13 lines>...
)
^
File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/hikari/impl/rest.py", line 2252, in edit_webhook_message
response = await self.\_request(route, json=body, query=query, auth=None)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/mnt/hdd/proj/high/in/CazzuBot/.venv/lib/python3.14/site-packages/hikari/impl/rest.py", line 925, in \_request
raise await net.generate_error_response(response)
hikari.errors.NotFoundError: Not Found 404: (10015) 'Unknown Webhook' for https://discord.com/api/v10/webhooks/1424584066295922710/aW50ZXJhY3Rpb246MTUzNTgwNDIyNjQzNTgxNzUzMjpuTEpkdnREeDh4VzlsRGNScHRvdktLNThDa1VRU0FDcE9pQldtNzZGeTJsaXJPZ21IM0NqSHdPYURTdHVNQzhYQjdSWUJMQlFmamVaRFlvcXhOQWpXS2piZWdibFNqS1lxaDVNMVFYQzZiOURGelV0TWhCSGpvM3Y2Qms3RU1DYw/messages/1535804226435817532?with_components=true

- [!] D4. `frog spawn` (manual), `frog fake`, `frog resync` (admin).

  Resync is similar issue to xp resync. Backlog.

  Spawn and fake seem to work.

  Big issue however.

  When a user presses the catch button, a message appears that the app is thinking. This shouldn't happen. It also for some reason is a reply to some earlier message. It never did this in the original pre-flash rewrite.

- [x] D5. **Restart while a spawn is live** → dangling frog message cleaned
  up on boot and a fresh spawn is re-queued.

- [~] D6. Quarterly freeze: set the freeze flag → inventory shows frozen
  frogs (or run a fake quarterly reset).

  ```
  Can't test this right now.
  ```

- [ ] D7. `/inventory` shows a member's frog holdings as a numbered
  inline-emoji grid (one embed, per-namespace header, empty state when the
  member has nothing). Verify the slot numbers are stable across repeated
  calls; the follow-up `/inventory consume (INDEX)` will address those
  slots.

## E. mod

Backlog all of mod. This isn't core nor is it finalized right now and is "in progress" in terms of development.
The mod plugin also **ships disabled** (`enabled = False` in `plugins/mod/__init__.py`) — it doesn't load
at boot; enable it with `/plugin enable mod` before working through this section.

- [ ] E1. `warn` → modlog entry + notification.

- [ ] E2. `mute 5m` → role applied, scheduled expiry row; **restart mid-mute**
  → unmute still fires on schedule.

- [ ] E3. `mute` with multi-word/compound durations (`2h30m`) — recent
  timeparse fix.

- [ ] E4. `kick`, `ban`, `unban`, `set mute`, `slowmode 10` — watch the
  hikari rate-limit timedelta handling (recent fix).

- [ ] E5. `mod_check` gate: non-mod gets a clean refusal; muting someone
  above the bot → clean error, no crash.

## F. poll

- [~] F1. `poll register` (modal) → `auto_populate` → `send` shows the vote
  menu.

  ```
  Auto populate should only show the user that items have been added, should not be a public message.
  ```

- [x] F2. Vote via the menu; **open the poll, restart the bot, vote again** —
  buttons stay alive across restarts (recent fix).

- [x] F3. Modal submit path, incl. the rules text in the vote input row (new
  UI — verify rules display and that votes register).

- [x] F4. `poll stats`, duplicate/closed poll behavior.

## G. welcome

- [x] G1. PENDING mode: development-guild member completes onboarding → welcome fires;
  double-welcome race guard holds.

- [x] G2. ROLE mode: member gains the monitored role (with several roles at
  once) → welcome fires exactly once (set-membership fix).

- [x] G3. `welcome enabled/verify/role/channel/message/mode/monitor/demo/raw`
  round-trip.

  This section G I didn't test very robustly, but it seems like it works.

## H. counter

- [!] H1. `counter create` → baka button message; clicks increment; expiry
  removes it.

  Clicking button. "This is not a baka counter anymore."

- [!] H2. **Restart, then click again** — custom-emoji buttons send the
  emoji **id**, not the tag (two recent fixes — live-verify).

  ```
  Blocked, see comment on H1.
  ```

## I. daily / quarterly

- [ ] I1. Missed-reset force: stop the bot, let midnight pass, boot → reset
  runs (log line + counts reset).

- [ ] I2. Quarterly freeze path via the same scheduler.

## J. fun

- [ ] J1. `ping` shows a sane heartbeat latency; `info` on a member and on a
  non-member; `echo`, `noot`, `hashiresoriyo`.

- [ ] J2. `register_inktober` + post "inktober day 5" with an attachment →
  👍 reaction (verifies MESSAGE_CONTENT intent); `scrape_inktober`
  downloads into `downloads/`.

- [ ] J3. `story compile` in a real channel (long scan → initial ack, final
  edit with stats, files written); `story write` chunks at 1900 chars.

## K. dev (hotswap)

- [ ] K1. `owner`, `calc to/cum`.

- [ ] K2. `archive_emojis` + `scrape` write files to `archives/` / `emojis/`.

- [ ] K3. **`plugin reload frogs` while running** → new code live, no
  double-registered commands; `plugin unload` removes the group from the
  tree; `plugin load` brings it back.

## L. window / feedback

- [ ] L1. Admin commands show the ✓/⚠︎/✖ prefixed ephemeral reply; invalid
  input paths flush an error window (no silent hangs).

- [ ] L2. Missing permissions on a command → clean message, not a bare
  "interaction failed".

## M. CLI tooling (roles / channels / snapshot / manifest)

Development guild only; always temp `--file` paths.

- [ ] M1. `snapshot fetch` → `data/roles_export.json`; `manifest lint` +
  `render` round-trip.

- [ ] M2. `roles export` (temp file) → `diff` → `apply --yes`: create,
  rename (`Old->New` rewrite), reorder, delete with `--delete`; backup
  snapshot written; `restore` re-applies; `check` exit codes.

- [ ] M3. `channels export/diff/apply/restore` with `--scope-below     <Category>`: reorder within a category, **slowmode seconds** (timedelta
  fix), text↔announcement conversion allowed, other type changes
  blocked, empty stray category delete.

- [ ] M4. Live CLI verbs work while the bot is offline.

## N. Robustness

- [ ] N1. Kill the network mid-run → gateway reconnects, scheduler continues
  from the `tasks` table, no duplicate ticks.

- [ ] N2. Long ops (resync, story compile, scrape) under rate limits — no
  429 cascade.

______________________________________________________________________

## Suggested order

A4–A7, B1, C1, D5, E2, F2, G2, H2 first — the migration-sensitive spots
(guild-dump timing, scheduler restart, component emoji ids, timedeltas,
component persistence). **Bold** items mark recent-fix areas worth verifying
live even with unit coverage.
