# Testing

How CazzuBot is tested, what each layer proves, and what still needs a live
Discord or a human. Read this before changing test infrastructure or
deciding whether a feature needs live verification.

## Strategy: three layers

Testing is layered by how much of the real framework runs, trading speed
and determinism against fidelity:

| Layer | Runs | Proves | Cost |
|---|---|---|---|
| 1. Unit tests | Pure logic + plugins with typed fakes | The logic is correct | milliseconds |
| 2. Offline interaction driver | Real bot, real lightbulb routing, fake REST | The feature works when a user touches it | seconds |
| 3. Manual / live | Real bot, real Discord (development guild) | Discord accepts it, real timing/events hold | minutes, human |

Rule of thumb: a change belongs in the highest layer that can express it.
Only what layer 2 cannot express falls through to layer 3.

---

## Layer 1 — unit tests

Location: `tests/core/`, `tests/plugins/<feature>/`, shared fakes in
`tests/fakes.py`, boot fixtures in `tests/conftest.py`.

What they are:

- **Service/logic tests** — parsers, validators, planners, db repositories,
  template verification, time parsing, scheduler logic. Pure functions and
  `Database` against a temp sqlite file. No framework objects at all
  (enforced by `tests/core/test_csr_boundary.py`).
- **Cog tests** — command classes invoked directly
  (`tests.fakes.invoke_command`) with a `FakeContext`, plus plugin db
  modules and scheduler handlers called by hand.
- **Boot tests** — a real `CazzuBot` constructed with a dummy token and
  driven through its lifecycle handlers (`_on_starting`/`_on_started`/
  `_on_stopping`) against a temp DB, with `FakeCache`/`FakeRest` injected.

What they prove: that each piece computes the right thing — exp math,
rank planning, manifest parsing, idempotent writes, schema drift refusal.

The boundary: they call handlers **directly**, so everything between
"Discord delivers an event" and "your handler runs" is skipped — event
deserialization, listener registration, lightbulb's menu/modal/command
routing, option conversion, checks/hooks, the error handler, and the
interaction-response lifecycle. A button that is never wired to its
handler passes unit tests and fails in production.

## Layer 2 — offline interaction driver

Location: `tests/driver.py`, integration scenarios in `tests/integration/`,
the `full_bot` fixture in `tests/conftest.py`.

The idea: **run the bot's real event pipeline, minus the network.** A
"press" is a synthetic gateway interaction (a JSON payload shaped exactly
like Discord's `INTERACTION_CREATE`) fed through hikari's **own**
deserializer (`bot.event_factory.deserialize_interaction_create_event`),
then dispatched through the real event manager (`bot.event_manager.dispatch
(event, return_tasks=True)`), which awaits every listener. A button press
therefore exercises the same code path a real Discord click takes:

```
gateway JSON → hikari deserializer → event manager → raw listeners
→ lightbulb routing (menu lookup by custom_id) → MenuContext/ModalContext
→ your callback → interaction methods → bot.rest (faked)
```

Only the last hop is faked. Everything before it — including the exact
hikari model shapes (`isinstance` checks included) — is real.

### The `full_bot` fixture

`boot_full_bot()` (and the `full_bot` fixture) boots a real `CazzuBot`
with **every plugin loaded**: real extensions registered through lightbulb,
real `on_load` hooks, real scheduler, temp database. Setup details:

- fakes are injected **before** the lifecycle starts, so plugin boot hooks
  never touch the network
- lightbulb's command-tree sync (the one network call at startup) is
  disabled while keeping the in-memory registration that routes
  interactions (`sync_commands = False`)
- owner checks are pre-warmed (`_owner_ids`) so prefab owner hooks
  short-circuit
- the lifecycle runs through the real event manager, so the lightbulb
  client actually starts (the plain `bot` fixture drives handlers directly
  and never starts its client)

### Driver API

- `run_slash(bot, "frog set enabled", options={...}, user_id=...)` — a
  slash command through the real command pipeline: option solving
  (including defaults and resolved channel/user options), CHECKS hooks
  (debug gate, owner/admin), error translation, window flows.
- `press_button(bot, custom_id=..., message_id=..., user_id=...)` — a
  component click (type 3 interaction).
- `submit_modal(bot, custom_id=..., values={...}, user_id=...)` — a modal
  submission (type 5).
- `wait_for_menu(bot)` / `wait_for_modal(bot, custom_id)` — lightbulb
  generates uuid custom ids for `add_interactive_button`; these discover
  them by label/emoji the way a user sees them.
- `modal_input_custom_id(modal)` — extract the uuid custom id of a modal's
  text input from the recorded modal response.
- Every call returns a `PressResult` with what the fake REST recorded
  during the dispatch: initial responses (type + payload), edits, deletes,
  follow-ups, modal responses, and any handler exceptions.

### Discord's interaction rules, modeled

The fake REST (`FakeRest` interaction endpoints) enforces the rules
Discord enforces, so lifecycle bugs fail loudly instead of passing
silently:

- **One initial response per interaction** — a second `create_interaction_response`
  raises `NotFoundError`, like Discord.
- **Webhook edits/deletes require an acked interaction** — editing via the
  interaction webhook before the click has an initial response 404s
  ("didn't respond in time" / `Unknown Webhook` class).
- **Messages are scoped per token** — a token can only manage its own
  webhook messages plus the message its button lives on (Discord's actual
  exception for component interactions).
- **`@original` only exists after a response type that materialises a
  message** — after a bare `DEFERRED_MESSAGE_CREATE`, edits/deletes/fetches
  of the initial response 404 like Discord.
- **A 3-second response budget** — every dispatch is awaited under
  `RESPONSE_BUDGET` (Discord's window), so a handler that never responds
  fails the test. Commands that legitimately block on a menu (`exp resync`
  waiting for a Yes/No) pass a larger `timeout=` instead.
- **Handler exceptions are captured** — hikari swallows listener failures
  into `ExceptionEvent`; the driver subscribes and surfaces them on the
  result, so a crashed callback is a test failure, not a log line.
- **Response types are assertable** — the "app is thinking" class
  (a `DEFERRED_*` where an immediate response was expected) is a plain
  assertion on the recorded type.

These rules are pinned by their own tests (`tests/integration/
test_driver_harness.py`).

### What layer 2 proves

- routing: custom ids reach the right handler; unknown/stale buttons are
  harmless; menus/modals resolve after "restarts" (reboot the bot on the
  same DB and press again)
- the command pipeline: option conversion, defaults, checks/gates, error
  translation into ephemeral replies, window reporting
- the interaction lifecycle: acks within budget, correct response types,
  correct edit/delete targets, wrong-user rejection, timeout cleanup
- concurrent presses (atomic increments), scheduler side effects
- everything assertable on the DB, the scheduler, or the recorded REST
  calls

## Layer 3 — manual / live verification

Location: `docs/MANUAL_TEST.md` (the checklist) against the **development
guild** (`CazzuBot Dev`). **The production guild is never mutated** — the
development guild is the only place mutating tests run, always with the
dev token.

The manual checklist is the fallback for everything the offline harness
cannot express, in these general categories:

- **Discord's server-side validation of outgoing payloads** — embed and
  component limits, emoji payloads, flag combinations, modal constraints.
  The fake accepts what Discord rejects; only a real API call proves the
  payload.
- **The real gateway lifecycle** — reconnect/resume after network failure,
  event ordering (guild dump vs ready), cache population, member chunking,
  privileged intents and developer-portal configuration.
- **Real timing and rate limits** — the actual 3-second window, 429
  cascades, latency under long operations, cooldowns under live traffic.
- **Two-real-user races** — e.g. a capture race where Discord's ordering
  of simultaneous interactions is the behavior under test.
- **Real event fidelity** — message shapes the harness never imagined
  (threads, attachments, message types), onboarding events, member-update
  reconstruction, channel-history scans.
- **Anything in the production guild** — read-only commands only, and only
  with explicit per-turn permission.

## Automation boundaries — general catalog

| Capability | Automated? | How |
|---|---|---|
| Logic: parsing, validation, math, db, templates | Yes | unit tests |
| Command semantics (handler body) | Yes | unit tests |
| Framework routing: slash → handler, button → menu, modal → submit | Yes | driver |
| Option conversion, defaults, resolved objects | Yes | driver |
| Checks & gates (owner/admin/debug) | Yes | driver |
| Error translation to ephemeral replies | Yes | driver |
| Interaction lifecycle: ack budget, response types, edit/delete targets | Yes | driver + fake rules |
| Wrong-user rejection, menu/modals timeouts | Yes | driver |
| Restart persistence (buttons survive a reboot) | Yes | driver (same DB, second boot) |
| In-process concurrency (atomic increments) | Yes | driver |
| Scheduled-task flows, missed-run force checks | Yes | unit + driver |
| CLI domain logic (roles/channels export/diff/plan) | Yes | unit tests (pure planners) |
| Payload acceptance by Discord | **No** | manual/live |
| Gateway behavior (reconnect, event ordering) | **No** | manual/live |
| Portal config, intents, command-tree sync | **No** | manual/live (one-time) |
| Rate limits, real timing | **No** | manual/live |
| Two-real-user races | **No** | manual/live (two accounts) |
| Real event fidelity | **No** | manual/live |
| CLI live verbs against real Discord | **No** | manual/live (development guild, temp manifests) |
| Production guild behavior | **No** | never automated; per-turn permission |

## Workflow

1. **Change a feature** → run `uv run pytest` (offline, fast).
   Add driver coverage in `tests/integration/` for anything interactive —
   a button, modal, or command whose routing/ack/lifecycle changed.
2. **Checks** → `uv run ruff check .` and `uv run ruff format .`
   (line-length 75, double quotes); basedpyright in the editor.
3. **Interactive changes** → before merging, either the driver test proves
   the flow end-to-end, or the scenario is added to `docs/MANUAL_TEST.md`
   for a live pass against the development guild.
4. **Live pass** → work through the checklist items the change touches;
   paste failures raw under the item. CLI verbs always use temp
   `--file` paths so production manifests are never clobbered.

## Future: automating layer 3

The remaining manual surface could be reduced with a development-guild
**user bot** (a separate Discord account driven programmatically) that
performs real
clicks, real slash invocations, and two-account races — covering payload
validation and event fidelity hands-free. It cannot cover gateway
reconnect behavior (needs network fault injection), rate-limit stress
(needs real traffic), or portal configuration (one-time setup). It is
ToS-grey territory (self-botting) and was deliberately deferred; the
offline driver above is the fast regression layer underneath it.
