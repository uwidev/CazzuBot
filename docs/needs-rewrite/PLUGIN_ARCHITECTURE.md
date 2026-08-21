# Plugin Design Architecture

This document pins how plugins compose in CazzuBot and records the ideas it
borrows from the Paper — *A Programming Paradigm for Spatiotemporal
Composability* (Yifan Shi, Wei Zhang — Peking University; Tianyi Cui —
DeepSeek-AI; the theory behind Cordis, the framework this bot's own harness
runs on). `paper.pdf` sits at the repo root (untracked) if you want the full
formal treatment.

## 1. The Paper, in plain language

Modern plugin systems recompose at runtime, but give no guarantees about it.
The paper identifies two orthogonal dimensions and builds a formal calculus
for both:

- **Temporal composability** — removing a component must *completely revert
  its side effects*. The paper's running failure: VSCode cannot unload one
  extension's code without restarting the whole extension host.
- **Spatial composability** — components *declare* the dependencies they need
  from the environment, and are *reactively notified* when those change. The
  paper's running failure: VSCode's `extensionDependencies` is barely used
  because inter-extension access goes through untyped `any` exports with no
  structural contract.

Two mechanisms deliver the guarantees:

1. **Revertible effects** — every effect returns not just "the new state" but
   also **its inverse**, supplied at the point of application. The runtime
   stacks inverses and, on removal, replays them **in reverse order**. The
   paper assumes each inverse is correct (level-1 trust) and *proves the
   compositional guarantee*: complete, order-correct teardown no matter how
   components interleave.
1. **Reactive coeffects** — a component declares a set of keys it needs; the
   runtime classifies every state change as *activating* (spec now
   satisfied → fire the component), *deactivating* (spec no longer
   satisfied → recover its effects), or *neutral*. Dependents activate after
   their providers and **deactivate before a provider withdraws**.

Three trust levels worth naming:

| Level                | What the runtime knows                                                       | Residual trust                                                                |
| -------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| 0                    | Nothing — unload means "call the hook, hope it cleans up"                    | The author wrote teardown *at all*, covering *everything*, in the right order |
| 1 (the paper)        | The exact list of effects, applied in order; unload replays undos in reverse | Only that *each* inverse is correct                                           |
| 2 (beyond the paper) | The inverse itself, because the creating API returned it                     | Nothing, for that effect                                                      |

Honest limits: the runtime cannot verify `undo∘apply = id` in general;
irreversible external effects need author-written *compensations*; the
calculus assumes an acyclic dependency order.

## 2. Pinned design (CazzuBot)

### 2.1 Composition state vs durable data

Unload recovers **what is active** — handlers, listeners, scheduler rows,
subscriptions, extensions. It **never touches durable data**: tables and
user rows survive unload by design. Uninstalling the frogs plugin must never
delete members' frogs; reloading experience resumes with lifetime exp
exactly as it was. The boot schema guard also permits *extra* tables, so
even a permanently-removed plugin leaves its data intact.

### 2.2 The lifecycle contract (`cazzubot/lifecycle.py`)

Every runtime effect declares its undo **at the point of application**:

- `load_plugin` auto-defers the framework-level effects it performs —
  `drop_tag(tag)` and handler-unregister per scheduled tag, and extension
  unloading.
- Plugins call `bot.lifecycle.defer(plugin_name, undo)` in `on_load` for
  custom effects (async or sync callables).
- `unload_plugin` calls `bot.lifecycle.withdraw(plugin)` — undos replay in
  reverse order, failures are logged and isolated (one bad undo never stops
  the cascade) — then runs `on_unload` (explicit teardown, e.g. the
  channels/roles drift-check plugins).

This is the paper's revertible-effects idea, level-1: teardown is
**structural** (the runtime knows what to undo, because it recorded it next
to the effect) rather than a hand-written hook the author must remember.

### 2.3 State-backed scheduling — "tasks are projections"

**The rule:** the source of truth for any pending work is a persisted row
(or code declaration) the plugin owns; **scheduler rows are projections** of
it. Therefore:

- **Unload withdraws all of a plugin's task rows** — safe, because they are
  derivable; nothing user-important lives only in the task table.
- **Every plugin with scheduled work re-arms from state in `on_load`** —
  cadences from their declarations (daily/quarterly/frog/board), one-shots
  from their data rows, applying overdue work immediately (catch-up).

Worked example — **mod expiries**: `modlog` (status='active' + `expires_on`)
is the truth; the `modlog` scheduler row is a wake-up call. On load, mod
drops stale projection rows and re-arms every ACTIVE row's deadline (or
applies it immediately if overdue); when an expiry fires, it reverts the
action and flips the modlog row to `pardon` so re-arming never repeats it.
A temp-ban expiry therefore survives unload/reload/restart by construction.

Accepted-minor exceptions (documented, low-stakes, self-healing): the
`board_weekly_close` poll timer and the `counter` footer expiry are cosmetic
one-shots — if withdrawn, the poll stays open until manual close / the next
weekly cadence, and the counter footer resets on the next interaction.

### 2.4 Withdrawal ordering (dependents first)

Unloading or reloading a provider also withdraws its **loaded dependents**
(transitively, SCC-aware), because their imports of the provider's modules
would otherwise go stale: unload dependents-first (reverse topological
order, purging module trees), reload dependencies-first. `plugin reload`
reports the full affected set.

### 2.5 Events

`bot.events.on()` returns an **unsubscribe token**; `off(event_type, handler)` removes a registration. Bus subscriptions are deferred effects —
a plugin hands the token to the lifecycle so unload withdraws its interest.
This is the reactive-coeffect idea in miniature: an observer declares
interest in a context change and is detached when deactivated.

### 2.6 Deliberate non-goals

- **No provisions/requires key registry** — plugin-granularity `depends_on`
  - boot-time topological ordering is enough for a single-guild bot that
    restarts deliberately.
- **No runtime dependency satisfaction re-evaluation** — the event bus is
  the reactive seam; plugins don't hot-swap providers mid-session.
- **No table-dropping unload** — durable data is never composition state.
- **Boot stays fail-fast** — a schema mismatch aborts loudly rather than
  withholding the component (manual deploys want loud failure).
- **No "keep pending rows" mechanism** — projections are withdrawn; truth is
  re-derived.

## 3. Level-2 opportunities (platform-returned disposables)

Where the platform already hands back an undo, use it instead of writing
one: scheduler `add` returns the row id, `bot.events.on` returns an
unsubscribe token. The lifecycle consumes either kind.

## 4. Mapping the paper onto CazzuBot

| Paper concept                                       | CazzuBot                                                   | Status                         |
| --------------------------------------------------- | ---------------------------------------------------------- | ------------------------------ |
| Coeffect declaration (what a component reads)       | `depends_on`, `asset_decl`, typed `SpeciesKey`/`FrogAsset` | Static, boot-time — deliberate |
| Revertible effects (undo co-located with apply)     | `bot.lifecycle.defer`/`withdraw`                           | Implemented                    |
| Reactive coeffects (notification on context change) | `bot.events` + unsubscribe tokens                          | Partial by design              |
| Witnessed inverse per application                   | Scheduler row ids, event tokens                            | Where platforms allow          |
| Dependents-before-withdrawal ordering               | `affected_by_unload` cascade                               | Implemented                    |
