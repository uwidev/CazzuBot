"""Frog spawning — the scheduler handler and capture flow.

Frogs spawn on a deterministic cadence ``interval ± fuzzy%``; each frog lives
``persist`` seconds. The next spawn is pre-rolled *before* the current frog is
spawned so a crashed/failed spawn never kills the schedule (as v1 did).
"""

import asyncio
import logging
import random
import time
from dataclasses import asdict
from typing import Any, cast

import hikari
import lightbulb
import pendulum

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot
from cazzubot.models import FrogTypeEnum, MemberSnapshot

from . import db as frog_db

_log = logging.getLogger(__name__)

FROG_EMOJI = "<:cirnoFrog:695126166301835304>"
FROG_NET_EMOJI = "<:cirnoNet:752290769712316506>"


async def on_frog_due(bot: CazzuBot, payload: dict[str, Any]) -> None:
    """Scheduler handler for tag ``frog``."""
    now = pendulum.now("UTC")
    cid = payload["cid"]
    interval = payload["interval"]
    persist = payload["persist"]
    fuzzy = payload["fuzzy"]

    # Safety: if frogs were disabled, the tasks should have been cleared, but
    # double-check anyway.
    if not await frog_db.get_enabled(bot.settings):
        return

    # Pre-roll the next spawn (from when this frog despawns) so a failure below
    # cannot kill the schedule.
    next_run = roll_future_frog(now.add(seconds=persist), interval, fuzzy)
    task_id = await bot.scheduler.add("frog", next_run, payload)

    try:
        captured = await spawn_and_wait(bot, persist, cid=cid)
    except hikari.InternalServerError:
        _log.warning(
            "discord server error while spawning frog; rescheduled"
        )
        return

    if captured and task_id is not None:
        # Reroll from the capture time for the next spawn.
        run_at = roll_future_frog(pendulum.now("UTC"), interval, fuzzy)
        await bot.scheduler.update_run_at(task_id, run_at)


async def spawn_and_wait(
    bot: CazzuBot,
    persist: int,
    ctx: lightbulb.Context | None = None,
    *,
    cid: int,
) -> bool:
    """Spawn a frog and wait for someone to capture it.

    The frog is a fresh message (frog emoji + Catch button) sent to ``cid``
    in a single payload. It lives ``persist`` seconds: pressing the button
    catches it and the message is deleted on the spot, otherwise the frog
    gets bored and the message is removed. Returns True if it was caught.

    ``ctx`` is the lightbulb context for the owner ``spawn``/``fake``
    commands (the frog becomes the slash response); without it the frog is
    sent to the channel directly.
    """
    menu = FrogCatchMenu(bot)
    if ctx is not None:
        response_id = await ctx.respond(
            FROG_EMOJI, components=cast(Any, menu)
        )
        message = await ctx.fetch_response(response_id)
        channel_id = ctx.channel_id
    else:
        channel = bot.cache.get_guild_channel(cid)
        if channel is None or not hasattr(channel, "send"):
            _log.warning("frog channel %s not found; skipping", cid)
            return False
        message = await cast(Any, channel).send(  # hasattr guard above
            FROG_EMOJI, components=cast(Any, menu)
        )
        channel_id = cid

    try:
        await menu.attach(bot.lightbulb, timeout=persist)
    except asyncio.TimeoutError:
        pass  # bored

    # caught or bored — either way the frog message goes away
    try:
        await bot.rest.delete_message(channel_id, message.id)
    except hikari.NotFoundError:
        pass
    return menu.captured


class FrogCatchMenu(lightbulb.components.Menu):
    """Capture button on a spawned frog; the first click wins.

    The menu itself never times out — the frog message's lifetime is owned
    by :func:`spawn_and_wait`, which deletes the message the moment the
    frog is caught or once it gets bored.
    """

    def __init__(self, bot: CazzuBot) -> None:
        super().__init__()
        self.bot = bot
        self.captured = False
        self._spawned_at = time.time()
        self.add_interactive_button(
            hikari.ButtonStyle.SUCCESS,
            self.catch,
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
        await mctx.defer()
        mctx.stop_interacting()  # unblocks spawn_and_wait, removes the frog

        uid = mctx.interaction.user.id
        now = pendulum.now("UTC")
        await frog_db.add_capture_log(
            self.bot.db,
            uid,
            now,
            waited_for=time.time() - self._spawned_at,
            frog_type=FrogTypeEnum.NORMAL,
        )
        await frog_db.modify_frog(
            self.bot.db, uid, modify=1, frog_type=FrogTypeEnum.NORMAL
        )
        await frog_db.modify_capture(self.bot.db, uid, modify=1)

        # send the capture message (user-configured template) as a followup
        msg_json = await frog_db.get_message(self.bot.settings) or {}
        frog_cnt_total = await frog_db.get_frogs(self.bot.db, uid)
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
        )
        content, embed, embeds = templates.prepare(msg_json)
        sent_id = await mctx.respond(
            content=content if content is not None else hikari.UNDEFINED,
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
        utils.schedule_delete(self.bot, mctx.channel_id, int(sent_id), 7)


async def queue_frog_spawns(bot: CazzuBot) -> None:
    """Insert one task per configured spawn channel."""
    for spawn in await frog_db.get_spawns(bot.db):
        payload = asdict(spawn)
        run_at = roll_future_frog(
            pendulum.now("UTC"), spawn.interval, spawn.fuzzy
        )
        await bot.scheduler.add("frog", run_at, payload)


async def reset_frog_tasks(bot: CazzuBot) -> None:
    """Clear all frog tasks and re-queue from the spawn settings."""
    _log.info("resetting frog spawn tasks...")
    await bot.scheduler.drop_tag("frog")
    if not await frog_db.get_enabled(bot.settings):
        return
    await queue_frog_spawns(bot)


def roll_future_frog(
    now: pendulum.DateTime, interval: int, fuzzy: float
) -> pendulum.DateTime:
    """Next spawn time: ``interval`` seconds, offset by ±``fuzzy``%."""
    offset = interval * (1 + roll_fuzzy(fuzzy))
    return now.add(seconds=offset)


def roll_fuzzy(fuzzy: float) -> float:
    return ((random.random() - 0.5) * 2) * fuzzy


def formatter(
    s: str,
    *,
    member: MemberSnapshot,
    frog_cnt_old: int | None = None,
    frog_cnt_new: int | None = None,
    seasonal_cap_old: int | None = None,
    seasonal_cap_new: int | None = None,
) -> str:
    """Placeholders: {avatar} {name} {mention} {id} {frog_cnt_old}
    {frog_cnt_new} {seasonal_cap_old} {seasonal_cap_new}"""
    return s.format(
        avatar=member.avatar_url,
        name=member.display_name,
        mention=member.mention,
        id=member.id,
        frog_cnt_old=frog_cnt_old,
        frog_cnt_new=frog_cnt_new,
        seasonal_cap_old=seasonal_cap_old,
        seasonal_cap_new=seasonal_cap_new,
    )
