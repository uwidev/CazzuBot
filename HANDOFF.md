# CazzuBot taskboard handoff — continue the remaining todo cards

Prepared 2026-09-07 for a fresh session. Read this file first, then `git status`
and `taskboard_list` before touching anything (parallel sessions may have moved
cards or the tree).

## Where you are

 -  Workspace / repo: `/mnt/hdd/proj/high/in/CazzuBot` (branch `prod`, HEAD
    `69dbdc6` — a WIP checkpoint; AGENTS.md is authoritative for conventions).
 -  DSH taskboard project id (workspaceId): `c7f1ea2e-e022-45aa-a69a-3b1bd443ca42`.
 -  Tool: load the `working-the-taskboard` skill, then list the board:
    `taskboard_list` (filter workspaceId + status=todo).
 -  The bot/venv: use `./.venv/bin/python` for pytest / ruff / basedpyright
    (`uv run` fails here because `~/.cache/uv` is read-only in this sandbox).

## Board discipline (condensed)

 -  Read a card (`taskboard_get` + comments) BEFORE claiming; comments are the
    latest requirements.
 -  Claim only `todo` cards in THIS project: `taskboard_move` todo→in_progress
    with the `ifVersion` you just read. On version conflict: re-read once,
    retry once if still claimable+unchanged, else stop and report.
 -  One card at a time; verify narrowly per AGENTS.md (touched tests +
    `ruff check .` + basedpyright, not the whole suite). Full suite once only
    when the user calls the run done.
 -  Hand off per card: `taskboard_comment_add` (what changed / how verified /
    outcome / risks), then `taskboard_move` in_progress→in_review. NEVER move a
    card to `done` — that is the user's confirmation. `backlog` is not
    approval to execute.

## Repo-state notes for this session

 -  Uncommitted work currently in the tree (from card `t-mtqhc488`, now
    in_review):
     -  `plugins/frogs/factory.py` — new `_arm_channel_spawn()` used by both
        `on_frog_due` and `queue_frog_spawns`; it REPLACES a channel's pending
        spawn row(s) inside one transaction so a channel never carries two
        armed rows (the root cause of intermittent double frogs).
     -  `tests/plugins/frogs/test_extension.py` — 2 regression tests for the
        above. Do not revert or duplicate this work; keep it as context.
 -  Pre-existing HEAD test failures (WIP checkpoint mismatch, NOT caused by
    the above; do not chase them unless a card explicitly asks):
     -  `tests/plugins/frogs/test_extension.py::test_frog_catch_captures_once`,
        `::test_frog_catch_sends_hardcoded_embed` (embed copy)
     -  `tests/plugins/frogs/test_cluster.py::test_cluster_catch_bursts_basics_into_zone`
        (title text "Cluster Frog burst!" vs "…just bursted!!")
     -  `tests/integration/test_frog_driver.py` (2 cluster/capture cases)
     -  `tests/plugins/frogs/test_species.py` (2 weight/shape cases)
 -  Live prod DB (read-only in sandbox): `/mnt/tmp/CazzuBot/data/cazzubot.db`
    — query with `sqlite3 'file:...?immutable=1'`. Dev DB: `data/cazzubot-dev.db`
    in the repo. NEVER modify prod files.

## Remaining claimable todo cards (all normal urgency, no comments, no
dependency edges) — suggested order

Lane grouping by files touched; if one session does them all, go in this
order; otherwise keep lanes on separate worktrees to avoid collisions.

### 1. `t-mtqhty5q-dak0vd` — assets re-upload investigation

Title: “Bot still uploads new assets rather than pulling the pre-existing
CDN url. Emojis seem fine, however.”  Description: it fails to discover the
pre-existing message/asset and re-uploads media on every boot.

 -  Look at `cazzubot/assets.py` (reconcile/publish path), `plugins/misc/
    asset.py`, asset DB (`asset` table), and how emoji assets reuse vs how
    IMAGE/media assets re-upload. Tests: `tests/core/test_assets.py`,
    `tests/plugins/misc/test_asset.py`.
 -  Fix the discovery gap; verify with the offline tests.

### 2. `t-mtrdhbbb-xbqfyo` — cluster blast radius within the channel category

Description: cluster-frog children currently spawn into hidden/sensitive
channels (position ±2 escapes the room); children should stay within the
same channel category as the origin channel. Also add a comment noting a
blacklist system as a potential future patch.

 -  Code: `plugins/frogs/behaviors.py` — `ClusterBurst._zone` (currently
    sorts guild text channels by (position, id), takes index ±2).
 -  Tests: `tests/plugins/frogs/test_cluster.py` (zone helpers + burst),
    `tests/integration/test_frog_driver.py` (cluster capture).

### 3. `t-mtrdkgho-rmqbcq` — cluster blast spawn-amount reweighting

Description: today 4–6 equal; user wants weighted 2–10, common 3–4, ~10%
chance to roll 10 — ideally generic/elegant without one weight per amount
(or explicit weights if that is clearest).

 -  Code: `plugins/frogs/behaviors.py` — `ClusterBurst.__call__`
    (`count = random.randint(4, 6)`). Keep `random` patchable for tests.
 -  Tests: same cluster files as card 2 (do 2 then 3 — same module).

### 4. `t-mtrdp0lw-7eu4j0` — `/inventory view` pagination gating

Description: page navigation should not show when the user has fewer than 25
unique items (one page fits).

 -  Code: `plugins/inventory/extension.py` (the view grid + button paginator
    reworked at HEAD by the in_review inventory cards).
 -  Tests: `tests/plugins/inventory/test_extension.py`,
    `tests/integration/test_inventory_driver.py`.

### 5. `t-mtrdv4ll-x2r2tm` — one shared frozen-frog consume path

Description: consuming any frozen frog should give the same error; today
there are 4 separate consume glues (`_consume_{basic,pog,froggers,classy}_
frozen`) for identical logic. Echoing WHICH frog is a nice-to-have but may
require changing the consume dispatcher shape — a generic “You can't consume
this frog” is acceptable if not trivial.

 -  Code: `plugins/frogs/items.py` (the four `_consume_*_frozen` funcs) + the
    item dispatch side (`consume=` glue signature).
 -  Tests: `tests/plugins/frogs/test_items.py` + inventory consume driver.

## Useful environment facts

 -  Run tests: `./.venv/bin/python -m pytest <path> -q`.
 -  Lint/format: `./.venv/bin/python -m ruff check .` and
    `./.venv/bin/python -m ruff format .`; types: `./.venv/bin/basedpyright`.
 -  `git commit` may hang on gpg signing in the sandbox — if committing,
    use `git -c commit.gpgsign=false commit …` (memory: sandbox has no gpg
    agent).
 -  repo `.env` has no `DB_PATH_DEV`; dev defaults to `data/cazzubot-dev.db`.
