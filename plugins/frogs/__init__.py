"""Frogs plugin package."""

from collections.abc import Callable

from cazzubot import Plugin
from cazzubot.bot import CazzuBot
from cazzubot.models import FrogItemKey
from cazzubot.statuses import (
    RoleConverger,
    ScopeKind,
    StatusesClearedEvent,
)
from cazzubot.scheduler import At
from typing_extensions import override

from . import db, factory
from .assets import FrogAsset
from .behaviors import ClusterBurst
from .items import FrogItems
from .seams import FrogSeam
from .species import by_key

# the season rollover: first instant of Jan/Apr/Jul/Oct — freezes every
# frog in place under its own species (frozen trophies; thaw is a gamble)
QUARTERLY_CADENCE = At(day=1, months=(1, 4, 7, 10), time="00:00")
# the frog half of the midnight reset: lifetime captures resync from the
# logs (the exp half lives in the experience plugin under tag ``daily``)
DAILY_CADENCE = At(time="00:00")

DAILY_FROG_TAG = "daily.frog"
QUARTERLY_TAG = "quarterly"


async def on_daily_frog_due(
    bot: CazzuBot, _payload: dict[str, object]
) -> None:
    """Scheduler handler for tag ``daily.frog`` — resync captures, re-arm.

    The two halves of the midnight reset run as independent rows on the
    same cadence (this one in frogs, ``daily`` in experience), so each
    keeps its own retry semantics.
    """
    await db.sync_with_frog_logs(bot.db)
    await bot.scheduler.arm(DAILY_FROG_TAG, DAILY_CADENCE)


async def on_quarterly_due(
    bot: CazzuBot, _payload: dict[str, object]
) -> None:
    """Scheduler handler for tag ``quarterly`` — season reset, then re-arm.

    Every fire is a season rollover by construction, so the reset is
    unconditional (and idempotent). Re-arming last keeps the fired row
    live while the reset runs, so a failed reset is retried.
    """
    await db.season_reset_frogs(bot.db)
    await bot.scheduler.arm(QUARTERLY_TAG, QUARTERLY_CADENCE)


class FrogsPlugin(Plugin):
    """Frogs plugin — spawn, capture and consume frogs via inventory."""

    name = "frogs"
    schema = db.SCHEMA
    extensions = ["plugins.frogs.extension", "plugins.frogs.reactions"]
    scheduled = {
        "frog": factory.on_frog_due,
        DAILY_FROG_TAG: on_daily_frog_due,
        QUARTERLY_TAG: on_quarterly_due,
    }
    # consuming frogs grants exp via the experience tables
    depends_on = ("experience",)
    asset_decl = FrogAsset
    item_decl = FrogItems

    # load-time wiring (set in on_load, withdrawn in on_unload): the
    # captured bot for the statuses-cleared revert, the classy-role
    # converger, and the event-bus unsubscribe token
    _bot: CazzuBot  # pyright: ignore[reportUninitializedInstanceVariable]
    _converger: RoleConverger  # pyright: ignore[reportUninitializedInstanceVariable]
    _unsub_cleared: Callable[[], None]  # pyright: ignore[reportUninitializedInstanceVariable]

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        # queue spawn tasks for any channels configured in a previous run
        await factory.reset_frog_tasks(bot)
        # clean up frog messages left dangling by a previous process
        await factory.cleanup_dangling_frogs(bot)
        # arm the cadences this plugin owns (capture resync, season reset)
        await bot.scheduler.arm_if_rowless(DAILY_FROG_TAG, DAILY_CADENCE)
        await bot.scheduler.arm_if_rowless(
            QUARTERLY_TAG, QUARTERLY_CADENCE
        )
        # inject the cluster catch implementation on the ClusterBurst instance the
        # species registry holds (behaviors → factory would cycle through
        # species; the plugin bridges them at load)
        burst = by_key(FrogItemKey.CLUSTER)
        if burst is not None and isinstance(burst.catch, ClusterBurst):
            burst.catch.spawn_impl = factory.spawn_and_wait  # pyright: ignore
        # register the classy-role converger (the external seam fails fast
        # on publish until one is registered) + revert instantly on clear
        self._bot = bot
        self._converger = RoleConverger(reason="classy frog role status")
        bot.statuses.register_converger(
            FrogSeam.CLASSY_ROLE, self._converger
        )
        self._unsub_cleared = bot.events.on(
            StatusesClearedEvent, self._on_statuses_cleared
        )

    @override
    async def on_unload(self, bot: CazzuBot) -> None:
        burst = by_key(FrogItemKey.CLUSTER)
        if burst is not None and isinstance(burst.catch, ClusterBurst):
            burst.catch.spawn_impl = None  # pyright: ignore
        bot.statuses.unregister_converger(FrogSeam.CLASSY_ROLE)
        self._unsub_cleared()

    async def _on_statuses_cleared(
        self, event: StatusesClearedEvent
    ) -> None:
        """Instant role revert when the statuses engine explicitly clears.

        The engine emits the event without an app, so the bot is captured
        on the plugin at load (``self._bot``).
        """
        if event.scope.kind is not ScopeKind.MEMBER:
            return
        if (
            event.seam is not None
            and event.seam != FrogSeam.CLASSY_ROLE.key
        ):
            return
        await self._converger(
            self._bot, event.scope, FrogSeam.CLASSY_ROLE.key
        )


plugin = FrogsPlugin()
