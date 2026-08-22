# Plan: typed fetch payloads — dataclass casting across the DB boundary

Status: **done — implemented** (all five phases; `633 passed`, ruff clean,
`basedpyright` clean for the touched modules — remaining tree errors are
pre-existing WIP). Implementation notes: `row_to`/`rows_to` now coerce by
field type in `cazzubot/db.py`; `Task`/`MemberEffectRow`/`AssetRow`/
`CounterRow`/`ModlogEntry` models added; `MemberExp.cdr`, `RankThreshold.mode`,
`Poll.open` switched to semantic types; boundary enforced by
`tests/core/test_db_boundary.py`; convention recorded in `AGENTS.md`.

Goal: standardize the casting of DB fetch payloads into usable dataclasses, so
every row crossing the DB boundary is a typed model (LSP/autocomplete-safe)
instead of a raw `aiosqlite.Row` or a hand-parsed `str` timestamp.

## Background / motivation

Two backlog frictions share one root cause — the DB boundary is not typed:

1. `docs/needs-rewrite/BACKLOG.md` — "dev friendly timestamp to sqlite
   compatible format time": `pendulum.now("UTC").to_iso8601_string()` gives no
   hint that this is the sqlite-encoding step, and nowhere is encode/decode
   named as a pair (`.isoformat()` and `.to_iso8601_string()` are both in use).
1. Un-typed fetch payloads: `fetchone`/`fetchall` return `aiosqlite.Row` whose
   `row["x"]` is `Any` to the LSP. `fetch_model`/`row_to` exist to fix this
   but (a) `row_to` only *maps* column names to fields, it never *converts*
   types, and (b) the pattern is not enforced across the tree.

The decision: make `row_to`/`rows_to` convert values by field type, give row
models **semantic** types (`pendulum.DateTime`, enums, `bool`), and enforce a
model boundary with a whole-tree sweep test — the same pattern as
`tests/core/test_csr_boundary.py` and `tests/core/test_command_guards.py`.

## Current audit

| Module                       | Fetch pattern                                               | Leak                                                                           | Action                                                            |
| ---------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| `plugins/counter/db.py`      | `by_id`/`by_mid` return `aiosqlite.Row \| None`             | Raw `Row` is a public return type; `counter/extension.py` does `counter["id"]` | Add `CounterRow` model; convert consumers                         |
| `plugins/mod/db.py`          | `fetchall` → manual `pendulum.parse` loop                   | Hand-rolled conversion, str timestamps                                         | Add `ModlogEntry` model                                           |
| `plugins/experience/db.py`   | `MemberExp` model, `cdr: str \| None`                       | Wrong-grained type; consumers parse by hand (`logic.py`)                       | `cdr → pendulum.DateTime \| None`                                 |
| `plugins/ranks/db.py`        | `RankThreshold.mode: str`                                   | Should be `WindowEnum`                                                         | Field type change                                                 |
| `plugins/poll/db.py`         | `Poll.open: int`                                            | Should be `bool`                                                               | Field type change                                                 |
| `plugins/board/db.py`        | `BoardRow.ts: str`; `latest_ts` → str                       | Opaque timestamp                                                               | Evaluate per-field (default: no change; `ts` feeds JSON payloads) |
| `plugins/frogs/db.py`        | `Spawn` clean; `FrogItem.parse`; `FrogItem` typed identity  | Manual re-parse at read boundary                                               | Leave `parse` (identity parsing, not row coercion)                |
| `cazzubot/scheduler.py`      | `Task.from_row` manually parses payload JSON; `run_at: str` | Separate hand-rolled conversion                                                | `Task.from_row` → `row_to`; `run_at → pendulum.DateTime`          |
| `cazzubot/settings.py`       | `load_json` on raw rows                                     | Already typed via `load_json`                                                  | No model needed (JSON key-value store)                            |
| `cazzubot/member_effects.py` | `pendulum.parse(row["expires_at"])`                         | Manual parse next to a table owner                                             | Model or typed coercion review                                    |
| `cazzubot/assets.py`         | `fetchone`/`fetchall` raw rows                              | Table owner without models                                                     | Model if rows are rows; else declare typed return                 |

Stays typed-but-not-a-model: scalars (`fetchval`), aggregate/ranked rows
(`list[tuple[int, int, int]]` via `rank_rows`), inventory `(item, qty)` pairs.
Forcing dataclasses on projections is ceremony — the rule is *row fetches →
models; projections/scalars → precise tuples/scalars*.

## Decisions (confirmed)

- **D1 Coercion set** — `row_to`/`rows_to` convert by field type; everything
  else passes through. Non-coercible values raise with a clear message.
- **D2 Model field policy** — full semantic types (DateTime, enums, bool);
  payload/transport strings stay `str` at the JSON boundary.
- **D3 Projections stay typed tuples/scalars** — no dataclass ceremony for
  aggregate/ranked rows.
- **D4 Scope** — all row-returning code: `plugins/*/db.py` **plus** core table
  owners (`scheduler`, `settings`, `member_effects`, `assets`).
- **D5 Model granularity** — one dataclass per *row shape*, not per query
  (projections reuse the same model; `row_to` maps `row.keys()`). A shape that
  repeats across features earns a shared model/generic store (the repo's
  existing convention: shared enums in `cazzubot/models.py`, generic
  `inventory`/`member_effects` stores). The generalized piece is the coercion
  machinery itself — `row_to`/`_coerce_field` work for any dataclass. No
  catch-all generic row type: it reintroduces column ambiguity and defeats the
  LSP goal.

## Coercion spec

| Stored (sqlite)      | Field type             | Direction                                             |
| -------------------- | ---------------------- | ----------------------------------------------------- |
| `TEXT` ISO-8601 UTC  | `pendulum.DateTime`    | `load` via `parse_iso8601`; already-typed passthrough |
| `TEXT` enum `.value` | `Enum` subclass        | `FieldType(value)`; `ValueError` → boundary error     |
| `TEXT` JSON          | `dict` / `list`        | `load_json`                                           |
| INTEGER 0/1          | `bool`                 | `bool(value)` (passthrough ints stay ints)            |
| anything else        | same type              | passthrough                                           |
| `X \| None` fields   | `X` with None handling | coerce the non-None side                              |

`row_to` keeps its current contract: iterates `row.keys()`, projected SELECTs
with fewer columns than model fields still work, constructor remains the honest
boundary (now *stronger*: conversion failures raise named errors instead of
silently flowing a `str` into a `DateTime` field).

## Phases

### Phase 1 — coercion machinery (`cazzubot/db.py`)

- `_coerce_field(field_type, value)` supporting `X | None` unions
  (`get_origin`/`get_args`), `pendulum.DateTime`, `Enum`, `dict`/`list` JSON,
  `bool`, and already-typed passthrough.
- Wire into `row_to`/`rows_to`; `fetch_model`/`fetch_models` inherit it.
- `functools.lru_cache` on per-model `get_type_hints` (scheduler ticks every
  second — don't pay per row).
- Tests in `tests/core/test_db.py`: round trips per coercion, `None` handling,
  bad-value raising, already-typed passthrough, union fields.

### Phase 2 — model inventory & conversion

- `plugins/counter/db.py`: `CounterRow(id, mid)`; `by_id`/`by_mid` →
  `CounterRow | None`; fix `plugins/counter/extension.py` row indexing.
- `plugins/mod/db.py`: `ModlogEntry` with `log_type: ModlogTypeEnum`,
  `given_on: pendulum.DateTime`, `status: ModlogStatusEnum`,
  `expires_on: pendulum.DateTime | None`, `reason: str | None`;
  `pending_expiries` builds tuples from models (ripple check in
  `plugins/mod/__init__.py`).
- `plugins/experience/db.py`: `MemberExp.cdr → pendulum.DateTime | None`;
  drop the `parse_iso8601(cdr)` at the consumer.
- `plugins/ranks/db.py`: `RankThreshold.mode → WindowEnum`.
- `plugins/poll/db.py`: `Poll.open → bool` (verify `WHERE open = ?` params
  still bind `1`).
- `cazzubot/scheduler.py`: `Task.from_row` → `row_to(Task, row)` with
  `run_at: pendulum.DateTime`; simplify `_is_stale`.
- `plugins/board/db.py` + `plugins/frogs/db.py`: evaluate `BoardRow.ts` and
  `FrogItem` as candidate changes; default no change unless a consumer needs
  the semantic type.

### Phase 3 — consumer sweep

- Delete now-dead `pendulum.parse`/`parse_iso8601` sites next to models.
- Replace `row["key"]` accesses with model attribute access.
- Drop unnecessary `.value` where enums are now typed.

### Phase 4 — enforcement

- New `tests/core/test_db_boundary.py` (AST sweep, `test_csr_boundary.py`
  style): no public db-module/db-owning-service function returns
  `aiosqlite.Row`/`Any`/bare `dict`; row-returning functions declare a model
  or a precise tuple/scalar.
- Update `cazzubot/db.py` docstring + `AGENTS.md` convention line: "row
  fetches return models; coercion lives in `row_to`".

### Phase 5 — verify

- `uv run ruff check .`, `uv run basedpyright`, `uv run pytest`.
- Fix every leak the new boundary test surfaces.

## Gotchas

- `from __future__ import annotations` (e.g. `member_effects.py`) makes hints
  strings — coercion must always resolve through `get_type_hints`.
- `slots=True` frozen dataclasses: coercion must return new values, never
  mutate in place.
- Enum coercion errors must be clear boundary errors (column + value + field),
  not a bare `ValueError` from `Enum(...)` internals.
- Bool fields: `True == 1` keeps existing SQL params working, but sweep
  `poll.open` consumers for literal `== 1` comparisons.
- Scheduler/settings payloads are JSON text — never bind `DateTime` into
  `json.dumps`; rich types exist only on row models, payload boundary stays
  `str`.

## Out of scope (follow-ups)

- Write-side timestamp ergonomics (`dump_timestamp`/`now_ts`, optional
  sqlite adapter for `DateTime` params) — the other half of the timestamp
  backlog; this plan only standardizes the read side.
- Making the model boundary a hard lint rule (beyond the AST sweep test).
