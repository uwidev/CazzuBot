"""Frog spawning — the scheduler handler and capture flow.

Frogs spawn on a deterministic cadence ``interval ± fuzzy%``; each frog lives
``persist`` seconds. The next spawn is pre-rolled *before* the current frog is
spawned so a crashed/failed spawn never kills the schedule (as v1 did).
"""

import asyncio
import logging
import random
import time
from typing import Any

import discord
import pendulum
from discord.utils import MISSING

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot
from cazzubot.models import FrogTypeEnum

from . import db as frog_db

_log = logging.getLogger(__name__)

FROG_EMOJI = "<:cirnoFrog:695126166301835304>"
FROG_NET_EMOJI = "<:cirnoNet:752290769712316506>"


def roll_fuzzy(fuzzy: float) -> float:
    return ((random.random() - 0.5) * 2) * fuzzy


def roll_future_frog(
    now: pendulum.DateTime, interval: int, fuzzy: float
) -> pendulum.DateTime:
    """Next spawn time: ``interval`` seconds, offset by ±``fuzzy``%."""
    offset = interval * (1 + roll_fuzzy(fuzzy))
    return now.add(seconds=offset)


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
    except discord.DiscordServerError:
        _log.warning(
            "discord server error while spawning frog; rescheduled"
        )
        return

    if captured and task_id is not None:
        # Reroll from the capture time for the next spawn.
        run_at = roll_future_frog(pendulum.now("UTC"), interval, fuzzy)
        await bot.scheduler.update_run_at(task_id, run_at)


class FrogCatchView(discord.ui.View):
    """Capture button on a spawned frog; the first click wins.

    The view itself never times out — the frog message's lifetime is owned
    by :func:`spawn_and_wait`, which deletes the message the moment the
    frog is caught or once it gets bored.
    """

    def __init__(self, bot: CazzuBot) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.captured = False
        self._spawned_at = time.time()

    @discord.ui.button(
        # label="Catch",
        style=discord.ButtonStyle.success,
        emoji=FROG_NET_EMOJI,
    )
    async def catch(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[Any],
    ) -> None:
        if self.captured:
            await interaction.response.send_message(
                "This frog was already caught.", ephemeral=True
            )
            return
        self.captured = True
        await interaction.response.defer()
        self.stop()  # unblocks spawn_and_wait, which removes the message

        uid = interaction.user.id
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

        # send the capture message (user-configured template)
        msg_json = await frog_db.get_message(self.bot.settings) or {}
        frog_cnt_total = await frog_db.get_frogs(self.bot.db, uid)
        seasonal = await frog_db.seasonal_captures(
            self.bot.db, uid, now.year, (now.month - 1) // 3
        )
        utils.deep_map(
            msg_json,
            formatter,
            member=interaction.user,
            frog_cnt_old=frog_cnt_total - 1,
            frog_cnt_new=frog_cnt_total,
            seasonal_cap_old=seasonal - 1,
            seasonal_cap_new=seasonal,
        )
        content, embed, embeds = templates.prepare(msg_json)
        if embed:
            msg = await interaction.followup.send(
                content=content if content is not None else MISSING,
                embed=embed,
                wait=True,
            )
        elif embeds:
            msg = await interaction.followup.send(
                content=content if content is not None else MISSING,
                embeds=embeds,
                wait=True,
            )
        else:
            msg = await interaction.followup.send(
                content=content or "_ _", wait=True
            )
        # followup.send is a webhook (no delete_after kwarg) — delete manually
        await msg.delete(delay=7)


async def spawn_and_wait(
    bot: CazzuBot,
    persist: int,
    interaction: discord.Interaction | None = None,
    *,
    cid: int,
) -> bool:
    """Spawn a frog and wait for someone to capture it.

    The frog is a fresh message (frog emoji + Catch button) sent to ``cid``
    in a single payload. It lives ``persist`` seconds: pressing the button
    catches it and the message is deleted on the spot, otherwise the frog
    gets bored and the message is removed. Returns True if it was caught.
    """
    channel = bot.get_channel(cid)
    if not isinstance(channel, discord.abc.Messageable):
        _log.warning("frog channel %s not found; skipping", cid)
        return False

    view = FrogCatchView(bot)
    if interaction:
        await interaction.response.send_message(FROG_EMOJI, view=view)
        # send_message returns an InteractionCallbackResponse (no .delete);
        # fetch the actual message so catch/boredom can remove it.
        message = await interaction.original_response()
    else:
        message = await channel.send(FROG_EMOJI, view=view)

    try:
        await asyncio.wait_for(view.wait(), timeout=persist)
    except asyncio.TimeoutError:
        pass  # bored

    # caught or bored — either way the frog message goes away
    try:
        await message.delete()
    except discord.NotFound:
        pass
    return view.captured


def formatter(
    s: str,
    *,
    member: discord.Member,
    frog_cnt_old: int | None = None,
    frog_cnt_new: int | None = None,
    seasonal_cap_old: int | None = None,
    seasonal_cap_new: int | None = None,
) -> str:
    """Placeholders: {avatar} {name} {mention} {id} {frog_cnt_old}
    {frog_cnt_new} {seasonal_cap_old} {seasonal_cap_new}"""
    return s.format(
        avatar=member.display_avatar.url,
        name=member.display_name,
        mention=member.mention,
        id=member.id,
        frog_cnt_old=frog_cnt_old,
        frog_cnt_new=frog_cnt_new,
        seasonal_cap_old=seasonal_cap_old,
        seasonal_cap_new=seasonal_cap_new,
    )


async def reset_frog_tasks(bot: CazzuBot) -> None:
    """Clear all frog tasks and re-queue from the spawn settings."""
    _log.info("resetting frog spawn tasks...")
    await bot.scheduler.drop_tag("frog")
    if not await frog_db.get_enabled(bot.settings):
        return
    await queue_frog_spawns(bot)


async def queue_frog_spawns(bot: CazzuBot) -> None:
    """Insert one task per configured spawn channel."""
    for spawn in await frog_db.get_spawns(bot.db):
        payload = dict(spawn)
        run_at = roll_future_frog(
            pendulum.now("UTC"), payload["interval"], payload["fuzzy"]
        )
        await bot.scheduler.add("frog", run_at, payload)
