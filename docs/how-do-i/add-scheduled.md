How do I… add scheduled work
============================

Delayed and recurring work goes through the **central scheduler**. One loop
polls the `tasks` table every second and dispatches due rows to the handler
registered for their tag — so tasks survive restarts.


1. Write the handler and register the tag
-----------------------------------------

Handler signature: `(bot, payload)`. Re-arm by adding the next row.

`plugins/<name>/__init__.py`:

~~~~ python
from cazzubot.scheduler import At


async def on_backup_due(bot, payload):
    await do_backup(bot.db)
    await bot.scheduler.arm("badges.backup", BACKUP_CADENCE)


BACKUP_CADENCE = At(time="03:00")


class BadgesPlugin(Plugin):
    name = "badges"
    scheduled = {"badges.backup": on_backup_due}
~~~~

The `counter` plugin does exactly this with a relative one-shot timer
instead of a cadence:

~~~~ python
await bot.scheduler.add(
    "counter",
    pendulum.now("UTC").add(hours=RECENT_WINDOW_HOURS),
    {"mid": mid, "cid": cid},
)
~~~~


2. Schedules
------------

Build schedules with `cazzubot.scheduler`:

 -  `At(time="03:00")` — daily at a UTC time.
 -  `At(weekday=0, time="09:00")` — weekly (0 = Monday … 6 = Sunday), or a
    tuple of weekdays for several days a week.
 -  `At(day=1, months=(1, 4, 7, 10), time="00:00")` — monthly; `day` can be a
    tuple (e.g. `(15, -1)`; negative counts from month end), `months` narrows
    it.
 -  `In(interval)` / `AtChaotic` / `InChaotic` — relative or randomly-rolled
    runs (frogs spawn with `interval ± jitter`).


3. Arm from state on load
-------------------------

Scheduler rows are **projections** — the source of truth is your data. On
boot, re-arm pending work from state so nothing is lost across a restart:

~~~~ python
async def on_load(self, bot):
    await bot.scheduler.arm_if_rowless(TAG, CADENCE)  # never clobber a row
    await bot.scheduler.arm(TAG, CADENCE)  # or replace the row
~~~~

`arm` drops `tag`'s rows and schedules the next occurrence; `arm_if_rowless`
only arms when no row exists (use it for cadences — mod re-arms every active
expiry from the modlog in `plugins/mod/__init__.py`).


4. Retry and missed runs
------------------------

A task without `retry: True` resolves whether or not its handler raised. To
guarantee handling, register `(handler, TaskPolicy)` — retries with backoff,
and `stale_after` drops rows that came due while the bot was down.

~~~~ python
from cazzubot.scheduler import TaskPolicy

scheduled = {"badges.backup": (on_backup_due, TaskPolicy(max_attempts=3))}
~~~~
