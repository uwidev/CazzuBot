Baseline Governance
===================

What a baseline is
------------------

A baseline is a dated snapshot of the measured project state that a plan
depends on: verified facts (suites green, module shapes, key contracts),
not intentions. It exists so a plan can be checked against the real code
and so later work can detect drift.


Authority
---------

 -  Project authority: `AGENTS.md` (conventions, guild safety, architecture)
    and the design docs it indexes (`docs/ARCHITECTURE.md`,
    `docs/PLUGINS.md`, `docs/TESTING.md`, …).
 -  Baselines never override the code: when code and a baseline disagree,
    the code is current and the baseline is stale — update it.
 -  A plan cites the baseline entries it depends on; work that invalidates a
    cited entry updates the baseline in the same change.


Format
------

One file per dated entry under `baseline/YYYY-MM-DD-<slug>.md`, kept short
and factual. Entries that stop being true are marked stale rather than
silently rewritten.


Scope discipline
----------------

A baseline records *measured, durable* facts only — no plans, no TODOs,
no transient progress.
