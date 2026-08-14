"""Frog spawning — the scheduler handler and capture flow.

Frogs spawn on a pure chaotic timeline: each spawn fires on the row armed
by the previous fire, rolled ``interval ± fuzzy%`` from the fire instant —
independent of the frog's despawn or capture, so frogs may overlap. The
next row is scheduled *before* the current frog spawns so a crashed or
failed spawn never kills the schedule (as v1 did).

The visible frog is a **species**: the spawn rolls one by weight and the
catch button carries it in its custom_id (``frog:catch:{cid}:{key}``, so
the boot sweep can still recognise and clean up stale frogs).
"""

import asyncio
import logging
import time
from dataclasses import asdict
from typing import Any, cast

import hikari
import lightbulb
import pendulum

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot
from cazzubot.models import FrogState, MemberSnapshot, SpeciesKey
from cazzubot.scheduler import InChaotic

from . import db as frog_db
from .events import FrogCapturedEvent
from .species import by_key, roll_species

_log = logging.getLogger(__name__)

FROG_EMOJI = "<:cirnoFrog:695126166301835304>"
FROG_NET_EMOJI = "<:cirnoNet:752290769712316506>"

# the catch button custom_id prefix: frog:catch:<cid>:<species_key>
_CATCH_PREFIX = "frog:catch:"


async def on_frog_due(bot: CazzuBot, payload: dict[str, Any]) -> None:
    """Scheduler handler for tag ``frog`` — pure chaotic timeline.

    The next spawn is rolled from the fire instant, independent of this
    frog's despawn or capture, and scheduled BEFORE spawning so a spawn
    failure can't kill the schedule.
    """
    # Safety: if frogs were disabled, the tasks should have been cleared, but
    # double-check anyway.
    if not await frog_db.get_enabled(bot.settings):
        return

    next_run = InChaotic(
        interval=payload["interval"], jitter=payload["fuzzy"]
    ).next_run(pendulum.now("UTC"))
    await bot.scheduler.add("frog", next_run, payload)

    # the spawn channel may belong to the OTHER guild (rows armed while
    # the bot served it) — never spawn into it under this guild mode
    if not utils.channel_in_guild(bot, payload["cid"]):
        _log.warning(
            "frog spawn channel %s outside configured guild; skipping",
            payload["cid"],
        )
        return

    try:
        await spawn_and_wait(bot, payload["persist"], cid=payload["cid"])
    except hikari.InternalServerError:
        _log.warning(
            "spawn failed (server error); next spawn already scheduled"
        )


async def spawn_and_wait(
    bot: CazzuBot,
    persist: int,
    ctx: lightbulb.Context | None = None,
    *,
    cid: int,
    species_key: SpeciesKey | None = None,
) -> bool:
    """Spawn a frog and wait for someone to capture it.

    The species is rolled when ``species_key`` is None (the owner spawn/
    fake commands can force one for testing). The frog is a fresh message
    (species name + art + Catch button) sent to ``cid`` in a single
    payload. It lives ``persist`` seconds: pressing the button catches it
    and the message is deleted on the spot, otherwise the frog gets bored
    and the message is removed. Returns True if it was caught.

    ``ctx`` is the lightbulb context for the owner ``spawn``/``fake``
    commands (the frog becomes the slash response); without it the frog is
    sent to the channel directly.
    """
    if species_key is None:
        species_key = roll_species().key
    menu = FrogCatchMenu(bot, cid, species_key)
    content = await _frog_content(bot, species_key)
    if ctx is not None:
        response_id = await ctx.respond(
            content, components=cast(Any, menu)
        )
        message = await ctx.fetch_response(response_id)
        channel_id = ctx.channel_id
    else:
        channel = utils.text_channel(bot, cid)
        if channel is None:
            _log.warning("frog channel %s not found; skipping", cid)
            return False
        message = await channel.send(content, components=cast(Any, menu))
        channel_id = cid

    # remember the frog message so a crashed process can clean it up on
    # the next boot (the catch button dies with the menu attachment)
    await frog_db.add_frog_message(bot.db, channel_id, message.id)

    try:
        await menu.attach(bot.lightbulb, timeout=persist)
    except asyncio.TimeoutError:
        pass  # bored

    # caught or bored — either way the frog message goes away
    try:
        await bot.rest.delete_message(channel_id, message.id)
    except hikari.NotFoundError:
        pass
    await frog_db.drop_frog_message(bot.db, channel_id, message.id)
    return menu.captured


async def _frog_content(bot: CazzuBot, species_key: SpeciesKey) -> str:
    """The spawned frog's message text: species name + its art URL."""
    species = by_key(species_key)
    name = species.name if species is not None else species_key.value
    art = await bot.assets.get(species.art) if species else None
    return f"{name}\n{art}" if art else name


class FrogCatchMenu(lightbulb.components.Menu):
    """Capture button on a spawned frog; the first click wins.

    The menu itself never times out — the frog message's lifetime is owned
    by :func:`spawn_and_wait`, which deletes the message the moment the
    frog is caught or once it gets bored.
    """

    def __init__(
        self, bot: CazzuBot, cid: int, species_key: SpeciesKey
    ) -> None:
        super().__init__()
        self.bot = bot
        self.captured = False
        self._spawned_at = time.time()
        self.species_key = species_key
        self.add_interactive_button(
            hikari.ButtonStyle.SUCCESS,
            self.catch,
            # a channel-scoped fixed id carrying the species; the prefix
            # lets the boot sweep recognise (and clean up) stale frogs
            custom_id=f"{_CATCH_PREFIX}{cid}:{species_key.value}",
            # buttons need the emoji id, not the <:name:id> tag
            emoji=utils.button_emoji(FROG_NET_EMOJI),
        )

    async def catch(self, mctx: lightbulb.components.MenuContext) -> None:
        if self.captured:
            await mctx.respond(
                "This frog was already caught.",
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return
        self.captured = True
        mctx.stop_interacting()  # unblocks spawn_and_wait, removes the frog

        await mctx.interaction.create_initial_response(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
        )

        uid: int | None = None
        try:
            uid = mctx.interaction.user.id
            now = pendulum.now("UTC")
            species = by_key(self.species_key)
            if species is None:
                _log.error(
                    "capture of unknown species %r (uid=%s)",
                    self.species_key.value,
                    uid,
                )
                return
            await frog_db.add_capture_log(
                self.bot.db,
                uid,
                now,
                waited_for=time.time() - self._spawned_at,
                species_key=species.key,
            )
            await frog_db.modify_inventory(
                self.bot.db,
                uid,
                species.key,
                FrogState.NORMAL,
                1,
            )
            await frog_db.modify_capture(self.bot.db, uid, modify=1)

            if species.catch_effect is not None:
                payload = species.catch_effect
                # the enum member's value IS the handler — no lookup
                await payload.key.value.catch(
                    self.bot,
                    payload,
                    uid=uid,
                    species_key=species.key,
                    now=now,
                )

            msg_json = await frog_db.get_message(self.bot.settings) or {}
            frog_cnt_total = await frog_db.total_inventory(
                self.bot.db, uid
            )
            seasonal = await frog_db.seasonal_captures(
                self.bot.db, uid, now.year, (now.month - 1) // 3
            )
            utils.deep_map(
                msg_json,
                formatter,
                member=utils.member_snapshot(mctx.interaction.user),
                frog_cnt_old=frog_cnt_total - 1,
                frog_cnt_new=frog_cnt_total,
                seasonal_cap_old=seasonal - 1,
                seasonal_cap_new=seasonal,
                species=species.name,
                species_art=(await self.bot.assets.get(species.art) or ""),
            )
            content, embed, embeds = templates.prepare(msg_json)
            sent = await self.bot.rest.create_message(
                mctx.channel_id,
                content=content
                if content is not None
                else hikari.UNDEFINED,
                embed=(
                    templates.embed_from_raw(embed)
                    if embed is not None
                    else hikari.UNDEFINED
                ),
                embeds=(
                    [templates.embed_from_raw(e) for e in embeds]
                    or hikari.UNDEFINED
                ),
            )
            utils.schedule_delete(
                self.bot, mctx.channel_id, int(sent.id), 7
            )
            # the sole FrogCapturedEvent emitter: observers subscribed via
            # bot.events.on (badges etc.) see the completed capture here;
            # failures are isolated by the bus and cannot break the catch
            await self.bot.events.emit(
                FrogCapturedEvent(
                    uid=uid,
                    species_key=species.key,
                    at=now.isoformat(),
                )
            )
        except Exception:
            # the click is already acked (and the frog removed by
            # spawn_and_wait) — a failure here is invisible to the catcher,
            # so it must at least hit the log
            _log.exception("frog capture processing failed (uid=%s)", uid)


async def queue_frog_spawns(bot: CazzuBot) -> None:
    """Insert one task per configured spawn channel."""
    for spawn in await frog_db.get_spawns(bot.db):
        payload = asdict(spawn)
        run_at = InChaotic(
            interval=spawn.interval, jitter=spawn.fuzzy
        ).next_run(pendulum.now("UTC"))
        await bot.scheduler.add("frog", run_at, payload)


async def reset_frog_tasks(bot: CazzuBot) -> None:
    """Clear all frog tasks and re-queue from the spawn settings."""
    _log.info("resetting frog spawn tasks...")
    await bot.scheduler.drop_tag("frog")
    if not await frog_db.get_enabled(bot.settings):
        return
    await queue_frog_spawns(bot)


async def cleanup_dangling_frogs(bot: CazzuBot) -> None:
    """Delete frog messages left by a previous process (dead buttons).

    Each tracked (channel, message) pair is re-checked at boot: if the
    message is gone (user/admin already cleaned up) or no longer carries
    the catch button (repurposed), the row is dropped silently; otherwise
    the dangling frog message is deleted.
    """
    rows = await frog_db.get_frog_messages(bot.db)
    for cid, mid in rows:
        try:
            message = await bot.rest.fetch_message(cid, mid)
        except hikari.NotFoundError:
            await frog_db.drop_frog_message(bot.db, cid, mid)
            continue
        if _is_frog_message(message, cid):
            try:
                await bot.rest.delete_message(cid, mid)
            except hikari.NotFoundError:
                pass
        await frog_db.drop_frog_message(bot.db, cid, mid)


def _is_frog_message(message: Any, cid: int) -> bool:
    """True when a message still carries the catch button for its channel.

    Matches by prefix so the species-bearing custom_id
    (``frog:catch:<cid>:<key>``) is recognised; the trailing colon keeps
    channel ids that prefix each other apart (``frog:catch:99:`` never
    matches a frog in channel 999).
    """
    wanted = f"{_CATCH_PREFIX}{cid}:"
    for row in message.components:
        for component in row.components:
            custom_id = getattr(component, "custom_id", None)
            if isinstance(custom_id, str) and custom_id.startswith(wanted):
                return True
    return False


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
