# Project Context — CazzuBot

## Canonical terms

  -  **status** (plural **statuses**) — persistent, scope-aware state
     applied to a scope: a contribution recorded against a member or the
     guild (user status, guild status, frog spawn status). Canonical
     owner of the concept: the status store (`cazzubot/statuses.py`,
     `bot.statuses`).
  -  **outcome** — the consequence of an action (consuming an item,
     catching a frog, a spawn hook). An outcome *may invoke statuses*,
     never the reverse — that is the boundary. Items compose their own
     outcomes (`_SPECIES_OUTCOMES`); the frog species-side outcome
     library is `plugins/frogs/outcomes.py::OutcomeKey`. (Species
     themselves composing outcomes like items do is a backlog item —
     see `docs/aegis/plans/2026-08-31-effects-to-statuses-outcomes.md`
     D5.)
  -  **seam** — a feature-declared input point on its own calculator;
     typed seams (`SeamKey`) address the status store. Unchanged by the
     2026-08-31 rename.

## Avoided aliases / overloaded names

  -  **effect / effects** — retired 2026-08-31 as a concept name; it was
     a catch-all (visual effects, cause-and-effect, side effects). Live
     generic-English uses ("side effects", "take effect") are not
     concepts.

## Relationships

  -  an item **composes** its **outcome**; an outcome **invokes**
     **statuses** through the status store
  -  a status is **applied to** a Scope (member or guild) and **pulled**
     by the feature that owns its seam