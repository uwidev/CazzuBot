"""Frog spawning — the scheduler handler and capture flow.

Frogs spawn on a pure chaotic timeline: each spawn fires on the row armed
by the previous fire, rolled ``interval ± fuzzy%`` from the fire instant —
independent of the frog's despawn or capture, so frogs may overlap. The
next row is scheduled *before* the current frog spawns so a crashed or
failed spawn never kills the schedule (as v1 did).
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
from cazzubot.models import FrogTypeEnum, MemberSnapshot
from cazzubot.scheduler import InChaotic

from . import db as frog_db

_log = logging.getLogger(__name__)

FROG_EMOJI = "<:cirnoFrog:695126166301835304>"
FROG_NET_EMOJI = "<:cirnoNet:752290769712316506>"


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
    menu = FrogCatchMenu(bot, cid)
    if ctx is not None:
        response_id = await ctx.respond(
            FROG_EMOJI, components=cast(Any, menu)
        )
        message = await ctx.fetch_response(response_id)
        channel_id = ctx.channel_id
    else:
        channel = utils.text_channel(bot, cid)
        if channel is None:
            _log.warning("frog channel %s not found; skipping", cid)
            return False
        message = await channel.send(
            FROG_EMOJI, components=cast(Any, menu)
        )
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


class FrogCatchMenu(lightbulb.components.Menu):
    """Capture button on a spawned frog; the first click wins.

    The menu itself never times out — the frog message's lifetime is owned
    by :func:`spawn_and_wait`, which deletes the message the moment the
    frog is caught or once it gets bored.
    """

    def __init__(self, bot: CazzuBot, cid: int) -> None:
        super().__init__()
        self.bot = bot
        self.captured = False
        self._spawned_at = time.time()
        self.add_interactive_button(
            hikari.ButtonStyle.SUCCESS,
            self.catch,
            # a channel-scoped fixed id: one frog per channel at a time, and
            # it lets the boot sweep recognise (and clean up) stale frogs
            custom_id=f"frog:catch:{cid}",
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

        # the capture message IS the interaction's first response: no defer
        # (no "app is thinking" bubble), no followup (not a reply) — the
        # click is acked in the same payload.
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
        if sent_id == utils.INITIAL_RESPONSE_IDENTIFIER:
            # the initial response's id is the sentinel, not the message id
            message = await mctx.fetch_response(
                utils.INITIAL_RESPONSE_IDENTIFIER
            )
            sent_id = message.id
        utils.schedule_delete(self.bot, mctx.channel_id, int(sent_id), 7)


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
    """True when a message still carries the catch button for its channel."""
    wanted = f"frog:catch:{cid}"
    for row in message.components:
        for component in row.components:
            if getattr(component, "custom_id", None) == wanted:
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
) -> str:
    """Placeholders: {avatar} {name} {mention} {id} {frog_cnt_old}
    {frog_cnt_new} {seasonal_cap_old} {seasonal_cap_new}"""
    return utils.format_member(
        s,
        member,
        frog_cnt_old=frog_cnt_old,
        frog_cnt_new=frog_cnt_new,
        seasonal_cap_old=seasonal_cap_old,
        seasonal_cap_new=seasonal_cap_new,
    )
