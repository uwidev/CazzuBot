# Project Context — CazzuBot

## Canonical terms

  -  **status** (plural **statuses**) — persistent, scope-aware state
     applied to a scope: a contribution recorded against a member or the
     guild (user status, guild status, frog spawn status). Canonical
     owner of the concept: the status store (`cazzubot/statuses.py`,
     `bot.statuses`).
  -  **outcome** — retired 2026-08-31 as a concept name: the frog
     outcome library (`plugins/frogs/outcomes.py::OutcomeKey`, payload
     dataclasses) dissolved into the status classes
     (`plugins/frogs/statuses.py`) and the species behaviors
     (`plugins/frogs/behaviors.py`). What consuming an item does is the
     **item's own written glue** over status classes; what catching or
     spawning a frog does is the **species' composed behavior**. Items
     compose statuses (invoked via `bot.statuses`), never the reverse —
     that boundary survives.
  -  **behavior** — code a species or item composes: a plain async
     callable owning what happens on an action (a species' `catch` /
     `spawn` hook, an item's `consume` glue). Values live on the status
     classes, not in payload objects.
  -  **seam** — a feature-declared input point on its own calculator;
     typed seams (`SeamKey`) address the status store. Unchanged by the
     2026-08-31 rename.

## Avoided aliases / overloaded names

  -  **effect / effects** — retired 2026-08-31 as a concept name; it was
     a catch-all (visual effects, cause-and-effect, side effects). Live
     generic-English uses ("side effects", "take effect") are not
     concepts.

## Relationships

  -  an item **composes** its **statuses** (its consume glue applies
     them via the status store); a species **composes behaviors**
     (`catch` / `spawn` callables)
  -  a status is **applied to** a Scope (member or guild) and **pulled**
     by the feature that owns its seam; the pull folds contributions by
     priority