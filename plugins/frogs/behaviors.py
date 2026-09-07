"""Frog species behaviors — the code species compose.

Species compose their behavior by writing code; the shared behaviors below
are the helpers a species may compose. Each is written next to its local
helpers (the Cluster burst keeps its zone math + child-spawn tracking here).

Two behaviors ship:
- ``grant_catch`` — the default catch of every item-granting species: +1 of
  the species' item to the catcher's inventory + the hardcoded capture
  announcement — the catcher's mention + ping on the message content, and
  an embed of the species' art emoji with the caught item's old→new stack,
  the season's captures and the total froggies old→new (see
  :func:`_default_capture_embed`).
  Species that just grant their item on capture compose *exactly
  this* (``catch=grant_catch``). A species that wants a custom catch writes
  its own behavior beside itself (nothing here forces a shape on it).
- ``ClusterBurst`` — the catch hook for Cluster Frog: catching the frog
  never grants an item (Cluster deliberately has no item) — instead the
  frog bursts 2–10 Basic frogs into the channels around the caught one (weighted low — see ``_burst_spawn_count``).
  Its child-spawning implementation is injected at plugin load
  (behaviors → factory would cycle; the plugin bridges), so this module
  never imports the factory.

This module is controller-shaped (like ``factory.py``): it imports hikari
and owns the spawn/capture + embed edge. ``species.py`` imports only the
behavior *values* from here and stays hikari-free.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any, cast

import hikari

from core import utils
from core.assets import emoji_cdn_url
from core.models import FrogItemKey, FrogState, MemberSnapshot
from core.tips import get_tip

from . import db as frog_db
from .assets import FrogAsset

if TYPE_CHECKING:
    from core.bot import CazzuBot

    from .species import Species

_log = logging.getLogger(__name__)

# the hardcoded capture announcement embed's color
_CAPTURE_COLOR = hikari.Color.from_hex_code("#a2dcf7")

# hikari-free channel-type check (hikari.ChannelType.GUILD_TEXT == 0)
_GUILD_TEXT = 0

# the cluster burst size roll — weighted 2–10: small blasts are the norm
# (3–4 the most common amounts), big bursts get less likely the larger
# they get, and 10 is a ~10% jackpot. One explicit weight per count; the
# tuple sums to 100 so each entry reads as its approximate percentage.
_BURST_MIN_COUNT = 2
_BURST_MAX_COUNT = 10
_BURST_COUNT_WEIGHTS = (12, 19, 19, 15, 10, 6, 5, 4, 10)  # counts 2..10


# -- catch behaviors ------------------------------------------------------


async def grant_catch(
    bot: "CazzuBot",
    *,
    uid: int,
    member: MemberSnapshot,
    species: "Species",
    now: Any,  # pendulum.DateTime
    cid: int,
    persist: int | None = None,
) -> hikari.Message:
    """The every-item-granting-species catch: +1 item and the capture message.

    Composed by each species that grants its item on capture
    (``species.catch = grant_catch``). The granted item is derived from the
    species key (``frog:<key>:normal`` — the frozen state is only
    reachable by season rollover, so a fresh capture always grants the
    normal item). The announcement message is hardcoded — set and forget;
    changing the text is a code change, not a runtime setting. The
    catcher's mention and ping live on the message **content**
    (``<@{uid}>``, with ``user_mentions=[uid]`` — Discord does not resolve
    pings inside embeds) and NOTHING else does: the embed carries the
    species' art emoji (published art yields its ``<:name:id>`` reference,
    unpublished art adds no emoji — never the literal "None"), the caught
    item's old→new stack, the season's captures old→new and the total
    froggies old→new, plus the CATCH_BANNER media asset's thumbnail
    (published only) and a cycling footer tip
    (see :func:`_default_capture_embed`). ``member`` supplies the footer
    icon. ``persist`` is also part of the contract (the frog's lifetime);
    the grant doesn't use it — behaviors like :class:`ClusterBurst` need
    it to size the children they spawn.
    """
    item_id = frog_db.FrogItem(species.key, FrogState.NORMAL).key
    await bot.inventory.add(uid, item_id)
    # Post-capture reads: the capture ledger (log + counter) already ran
    # before this behavior and the grant just added the item, so these
    # include the +1 — the "old" values are simply one less.
    species_new = await frog_db.get_inventory(bot.db, uid, species.key)
    frog_cnt_new = await frog_db.total_inventory(bot.db, uid)
    seasonal_new = await frog_db.seasonal_captures(
        bot.db, uid, now.year, utils.month2season(now.month)
    )
    # the species' art emoji rides the embed, beside the species name:
    # published art yields its <:name:id> reference, unpublished art adds
    # no emoji — never "None" (mirrors the spawn message's fallback)
    art = (
        await bot.assets.get(species.art)
        if species.art is not None
        else None
    )
    # the embed's thumbnail references the CATCH_BANNER media asset
    # (plugins/assets/caught.png) — its CDN URL when published, no
    # thumbnail while unpublished (mirrors the inventory grid's fallback)
    banner = await bot.assets.thumbnail_for(FrogAsset.CATCH_BANNER)
    payload: dict[str, Any] = {
        # the ping lives on the message content, outside the embed —
        # Discord does not resolve pings inside embeds, so the embed
        # description must not carry the catcher's mention
        "content": f"<@{uid}>",
        "embed": _default_capture_embed(
            member,
            species,
            art,
            banner=banner,
            species_old=species_new - 1,
            species_new=species_new,
            seasonal_old=seasonal_new - 1,
            seasonal_new=seasonal_new,
            frog_cnt_old=frog_cnt_new - 1,
            frog_cnt_new=frog_cnt_new,
        ),
    }
    # Least-permissive mention policy: explicitly allow mention of exactly
    # the catcher we're pinging (``user_mentions=[uid]``), never a blanket
    # "all users" / "all roles". The announcement is hardcoded — there is
    # no template ``allowed_mentions`` flag that could suppress the ping.
    # The behavior sends via ``rest.create_message`` directly, so it must
    # pass the mention kwargs itself — otherwise hikari's allowed_mentions
    # defaults to ``{parse:[]}`` and the catcher would never be pinged.
    sent = await bot.rest.create_message(
        cid,
        **payload,
        user_mentions=[uid],
        role_mentions=hikari.UNDEFINED,
        mentions_everyone=hikari.UNDEFINED,
    )
    utils.schedule_delete(bot, cid, int(sent.id), 7)
    return sent


def _default_capture_embed(
    member: MemberSnapshot,
    species: "Species",
    art: str | None,
    *,
    banner: str | None,
    species_old: int,
    species_new: int,
    seasonal_old: int,
    seasonal_new: int,
    frog_cnt_old: int,
    frog_cnt_new: int,
) -> hikari.Embed:
    """The hardcoded capture announcement embed.

    Mirrors the old ``frog.message`` template, now baked into code (set
    and forget): a "+1 to froggies" headline, the caught species' art
    emoji (published only) with its stack old→new, the season's captures
    old→new, the total frog count old→new ("froggies" = all species), the
    CATCH_BANNER media asset's thumbnail (its CDN URL while published, no
    thumbnail while unpublished) and a cycling footer tip (``get_tip`` via
    ``core.tips`` — this plugin's "frog" tip_sets) with the catcher's
    avatar. The catcher's mention and ping deliberately live on the message
    content (see :func:`grant_catch`) and NOT here — Discord does not
    resolve pings inside embeds.
    """
    embed = hikari.Embed(
        color=_CAPTURE_COLOR,
        title="Congrats on your catch!",
        description=(
            "+1 to froggies\n\n"
            f"**{species.name}**: `{species_old}` -> `{species_new}`\n"
            f"**Seasonal Captures**: `{seasonal_old}` -> `{seasonal_new}`\n"
            f"**Total Captures**: `{frog_cnt_old}` -> `{frog_cnt_new}`"
        ),
    )
    if banner:
        embed.set_thumbnail(banner)
    if art:
        emoji_url = emoji_cdn_url(art)
        embed.set_footer(icon=emoji_url, text=get_tip("frog"))
    else:
        embed.set_footer(text=get_tip("frog"))

    return embed


def _burst_spawn_count(rng: Any) -> int:
    """One weighted burst size (2–10) drawn from ``rng``.

    Cluster blasts are small most of the time (3–4 the most common
    amounts), larger bursts get less likely the bigger they get, and 10
    is a ~10% jackpot — ``_BURST_COUNT_WEIGHTS`` sums to 100 so each
    entry reads as its approximate percentage. ``rng`` is the injectable
    random source (the module ``random`` at call time, patched in tests).
    """
    return rng.choices(
        range(_BURST_MIN_COUNT, _BURST_MAX_COUNT + 1),
        weights=_BURST_COUNT_WEIGHTS,
    )[0]


class ClusterBurst:
    """The Cluster species' catch behavior: burst Basic frogs nearby.

    An instance is composed into ``SPECIES`` (Cluster's ``catch``): the
    frog spawns like any catchable frog, but catching it never grants an
    item (Cluster deliberately has no item) — the burst IS the catch. The
    child-spawning implementation is injected by the plugin at load
    (``spawn_impl = factory.spawn_and_wait``); this module never imports
    the factory, keeping the graph acyclic. Children run as tracked
    background tasks so the burst returns immediately.
    """

    def __init__(self) -> None:
        self.spawn_impl: Callable[..., Awaitable[bool]] | None = None
        # strong references keep background child tasks alive until done
        self._background: set[asyncio.Task[Any]] = set()

    async def __call__(
        self,
        bot: "CazzuBot",
        *,
        uid: int,
        member: MemberSnapshot,
        species: "Species",
        now: Any,  # pendulum.DateTime — catch-hook contract, unused here
        cid: int,
        persist: int,
    ) -> hikari.Message | None:
        """Burst: no item — 2–10 Basic frogs (weighted low, 10 is a ~10% jackpot) into the channels around ``cid``
        (kept within the caught channel's category).

        The capture ledger (log, counter, event) already ran before this
        behavior; the burst is the whole species behavior and never grants
        an item (``frog:cluster:*`` does not exist). The announcement
        mirrors the capture-message shape: the catcher's mention + ping
        and the species' art emoji ride on the message **content**
        (``user_mentions=[uid]`` — Discord does not resolve pings inside
        embeds), and the burst outcome — the Basic Frogs the failed catch
        burst into — is the "new count" line (there is no item stack to
        count for a burst, so the burst IS the catch). The embed carries
        no mention, and its thumbnail references the CATCH_BANNER media
        asset (published only), like the grant capture embed. Children
        then spawn as real Basic frogs living ``persist`` seconds,
        staggered 0.75s apart (the rate-limit guard). Returns the
        announcement message — None when the burst can't fire (no child
        implementation injected, or no zone to burst into).
        """
        if self.spawn_impl is None:
            _log.error(
                "ClusterBurst has no spawn_impl — plugin on_load missed"
            )
            return None
        zone = await self._zone(bot, bot.config.guild_id, cid)
        if not zone:
            _log.warning(
                "cluster catch channel %s outside text channels", cid
            )
            return None
        count = _burst_spawn_count(random)
        targets = [random.choice(zone) for _ in range(count)]
        _log.info(
            "cluster frog bursts %d basic(s) across %d channel(s)",
            count,
            len(zone),
        )
        # the announcement follows the capture-message convention (see
        # ``grant_catch``): the catcher's mention and ping ride on the
        # message content — Discord does not resolve pings inside embeds,
        # so the embed must not carry the catcher. Cluster frogs never
        # grant an item — there is no species stack to count; the burst
        # count (the Basic Frogs the failed catch burst into) is the
        # count line instead.
        content = f"<@{uid}>"
        sent = await bot.rest.create_message(
            cid,
            content=content,
            embed=await _burst_embed(bot, species, count),
            user_mentions=[uid],
            role_mentions=hikari.UNDEFINED,
            mentions_everyone=hikari.UNDEFINED,
        )
        utils.schedule_delete(bot, cid, int(sent.id), 7)
        for target in targets:
            self._start_child(bot, persist, target)
            await asyncio.sleep(0.75)  # the rate-limit guard
        return sent

    async def _zone(
        self, bot: "CazzuBot", guild_id: int, cid: int
    ) -> list[tuple[int, int]]:
        """(channel_id, position) of text channels ±2 around ``cid`` in its room.

        The blast stays **within the channel category** of the caught
        channel (its "room"): only text channels sharing the origin's
        ``parent_id`` (None for uncategorized channels, which form one
        implicit room) qualify, still ordered by (position, id) with the
        ±2 radius taken inside that room. A cluster catch can therefore
        never spill into a hidden/sensitive channel that merely sits next
        to the origin in the guild-wide position order (e.g. a staff-only
        announcements channel in an adjacent category). A future patch may
        add a per-channel deny-list a burst must never target — the zone
        narrowing above is the category-level containment; a blacklist
        would be the explicit override on top.
        """
        channels = await bot.rest.fetch_guild_channels(guild_id)
        by_id = {
            int(channel.id): channel
            for channel in channels
            if getattr(channel, "type", None) == _GUILD_TEXT
        }
        origin = by_id.get(cid)
        if origin is None:
            return []
        parent = getattr(origin, "parent_id", None)
        texts = [
            (
                int(channel.id),
                int(getattr(channel, "position", 0) or 0),
            )
            for channel in channels
            if (
                getattr(channel, "type", None) == _GUILD_TEXT
                and getattr(channel, "parent_id", None) == parent
            )
        ]
        texts.sort(key=lambda entry: (entry[1], entry[0]))
        ids = [entry[0] for entry in texts]
        if cid not in ids:
            return []
        index = ids.index(cid)
        return texts[max(0, index - 2) : index + 3]

    def _start_child(
        self, bot: "CazzuBot", persist: int, target: tuple[int, int]
    ) -> None:
        """Fire one child Basic-frog spawn as a tracked background task."""
        impl = self.spawn_impl
        if impl is None:
            _log.error(
                "ClusterBurst has no spawn_impl — plugin on_load missed"
            )
            return
        task = asyncio.create_task(
            cast(
                "Coroutine[Any, Any, bool]",
                impl(
                    bot,
                    persist,
                    cid=target[0],
                    species_key=FrogItemKey.BASIC,
                ),
            )
        )
        self._background.add(task)
        task.add_done_callback(self._background.discard)


async def _burst_embed(
    bot: CazzuBot,
    species: "Species",
    count: int,
) -> hikari.Embed:
    """The burst announcement embed — species + burst outcome.

    Its thumbnail references the CATCH_BANNER media asset (plugins/
    assets/caught.png — its CDN URL while published, no thumbnail while
    unpublished), like the grant capture embed, and it is mention-free:
    the catcher's mention and ping live on the message content in
    :class:`ClusterBurst` (Discord does not resolve pings inside embeds).
    Cluster Frogs are never actually caught — the copy says the catch
    failed but the frog burst into ``count`` Basic Frogs anyway (the
    burst IS the catch; no item is ever granted).
    """
    banner = await bot.assets.thumbnail_for(FrogAsset.CATCH_BANNER)
    embed = hikari.Embed(
        color=_CAPTURE_COLOR,
        title="Cluster Frog just bursted!!",
        description=(
            f"You made the Cluster frog burst into **`{count}`** Basic "
            "Frogs in the nearby channels!"
        ),
    )
    if banner:
        embed.set_thumbnail(banner)
    return embed
