"""Frog species behaviors — the code species compose.

Species compose their behavior by writing code; the shared behaviors below
are the helpers a species may compose. Each is written next to its local
helpers (the Cluster burst keeps its zone math + child-spawn tracking here).

Two behaviors ship:
- ``grant_catch`` — the default catch of every catchable species: +1 of the
  species' item to the catcher's inventory + the capture announcement embed.
  Species that just grant their item on capture compose *exactly this*
  (``catch=grant_catch``). A species that wants a custom catch writes its
  own behavior beside itself (nothing here forces a shape on it).
- ``ClusterBurst`` — the spawn hook for Cluster Frog: replaces the
  catchable frog at spawn time by bursting 4–6 Basic frogs into the
  channels around the spawn channel. Its child-spawning implementation is
  injected at plugin load (behaviors → factory would cycle; the plugin
  bridges), so this module never imports the factory.

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

from cazzubot import templates, utils
from cazzubot.models import FrogItemKey, FrogState, MemberSnapshot

from . import db as frog_db
from .assets import FrogAsset

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

    from .species import Species

_log = logging.getLogger(__name__)

# the built-in capture embed (used when no frog.message template is set)
_CAPTURE_COLOR = hikari.Color.from_hex_code("#a2dcf7")

# hikari-free channel-type check (hikari.ChannelType.GUILD_TEXT == 0)
_GUILD_TEXT = 0


# -- catch behaviors ------------------------------------------------------


async def grant_catch(
    bot: "CazzuBot",
    *,
    uid: int,
    member: MemberSnapshot,
    species: "Species",
    now: Any,  # pendulum.DateTime
    cid: int,
) -> hikari.Message:
    """The every-catchable-species catch: +1 item and the capture embed.

    Composed by each catchable species (``species.catch = grant_catch``).
    The granted item is derived from the species key (``frog:<key>:normal``
    — the frozen state is only reachable by season rollover, so a fresh
    capture always grants the normal item). The embed comes from the
    configured ``frog.message`` template when set, else the built-in
    :func:`_default_capture_embed`.
    """
    item_id = frog_db.FrogItem(species.key, FrogState.NORMAL).key
    await bot.inventory.add(uid, item_id)

    frog_cnt_total = await frog_db.total_inventory(bot.db, uid)
    seasonal = await frog_db.seasonal_captures(
        bot.db, uid, now.year, utils.month2season(now.month)
    )
    msg_json = await frog_db.get_message(bot.settings) or {}
    if msg_json:
        utils.deep_map(
            msg_json,
            formatter,
            member=member,
            frog_cnt_old=frog_cnt_total - 1,
            frog_cnt_new=frog_cnt_total,
            seasonal_cap_old=seasonal - 1,
            seasonal_cap_new=seasonal,
            species=species.name,
            species_art=(
                (await bot.assets.get(species.art) or "")
                if species.art is not None
                else ""
            ),
        )
        payload = templates.build_payload(msg_json)
    else:
        # no configured capture message — fall back to the built-in capture
        # embed rather than sending a blank message
        payload: dict[str, Any] = {
            "embed": await _default_capture_embed(
                bot, member, species, frog_cnt_total, seasonal
            )
        }
    # Least-permissive mention policy: explicitly allow mention of exactly
    # the catcher we're pinging (``user_mentions=[uid]``), never a blanket
    # "all users" / "all roles". The template's ``allowed_mentions`` flag
    # can only suppress (``false`` = ping nothing); it cannot broaden the
    # ping beyond the catcher. Unlike ``templates.send``, the behavior
    # sends via ``rest.create_message`` directly, so it must pass the
    # mention kwargs itself — otherwise hikari's allowed_mentions defaults
    # to ``{parse:[]}`` and the catcher would never be pinged.
    sent = await bot.rest.create_message(
        cid,
        **payload,
        user_mentions=(
            [uid]
            if msg_json.get("allowed_mentions") is not False
            else hikari.UNDEFINED
        ),
        role_mentions=hikari.UNDEFINED,
        mentions_everyone=hikari.UNDEFINED,
    )
    utils.schedule_delete(bot, cid, int(sent.id), 7)
    return sent


async def _default_capture_embed(
    bot: "CazzuBot",
    member: MemberSnapshot,
    species: "Species",
    frog_cnt_total: int,
    seasonal: int,
) -> hikari.Embed:
    """The built-in capture embed, used when no ``frog.message`` is set.

    Shows the catcher's mention, the species, and the post-capture counts
    (total inventory + this season's captures), with the :data:`FrogAsset`
    ``CATCH_BANNER`` media image as the thumbnail when it's published.
    """
    banner = await bot.assets.get(FrogAsset.CATCH_BANNER)
    embed = hikari.Embed(
        color=_CAPTURE_COLOR,
        title="Frog caught!",
        description=(
            f"{member.mention} caught a **{species.name}**!\n"
            f"Inventory: **`{frog_cnt_total}`** frog(s) • "
            f"This season: **`{seasonal}`** capture(s)"
        ),
    )
    if banner:
        embed.set_thumbnail(banner)
    return embed


def formatter(
    s: str,
    *,
    member: MemberSnapshot,
    frog_cnt_old: int | None = None,
    frog_cnt_new: int | None = None,
    seasonal_cap_old: int | None = None,
    seasonal_cap_new: int | None = None,
    species: str | None = None,
    species_art: str | None = None,
) -> str:
    """Placeholders: {avatar} {name} {mention} {id} {frog_cnt_old}
    {frog_cnt_new} {seasonal_cap_old} {seasonal_cap_new} {species}
    {species_art}"""
    return utils.format_member(
        s,
        member,
        frog_cnt_old=frog_cnt_old,
        frog_cnt_new=frog_cnt_new,
        seasonal_cap_old=seasonal_cap_old,
        seasonal_cap_new=seasonal_cap_new,
        species=species,
        species_art=species_art,
    )


# -- spawn behaviors ------------------------------------------------------


class ClusterBurst:
    """The Cluster species' spawn behavior: burst Basic frogs nearby.

    An instance is composed into ``SPECIES`` (Cluster's ``spawn``). The
    child-spawning implementation is injected by the plugin at load
    (``spawn_impl = factory.spawn_and_wait``); this module never imports
    the factory, keeping the graph acyclic. Children run as tracked
    background tasks so the scheduled spawn fires immediately.
    """

    def __init__(self) -> None:
        self.spawn_impl: Callable[..., Awaitable[bool]] | None = None
        # strong references keep background child tasks alive until done
        self._background: set[asyncio.Task[Any]] = set()

    async def __call__(
        self,
        bot: "CazzuBot",
        *,
        cid: int,
        guild_id: int,
        persist: int,
        now: Any,
    ) -> None:
        """Explode: 4–6 Basic frogs into the text channels around ``cid``."""
        if self.spawn_impl is None:
            _log.error(
                "ClusterBurst has no spawn_impl — plugin on_load missed"
            )
            return
        zone = await self._zone(bot, guild_id, cid)
        if not zone:
            _log.warning(
                "cluster spawn channel %s outside text channels", cid
            )
            return
        count = random.randint(4, 6)
        targets = [random.choice(zone) for _ in range(count)]
        _log.info(
            "cluster frog bursts %d basic(s) across %d channel(s)",
            count,
            len(zone),
        )
        for target in targets:
            self._start_child(bot, persist, target)
            await asyncio.sleep(0.75)  # the rate-limit guard

    async def _zone(
        self, bot: "CazzuBot", guild_id: int, cid: int
    ) -> list[tuple[int, int]]:
        """(channel_id, position) of text channels ±2 around ``cid``."""
        channels = await bot.rest.fetch_guild_channels(guild_id)
        texts = [
            (
                int(channel.id),
                int(getattr(channel, "position", 0) or 0),
            )
            for channel in channels
            if getattr(channel, "type", None) == _GUILD_TEXT
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
