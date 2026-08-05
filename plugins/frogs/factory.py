"""Frog spawning — the scheduler handler and capture flow.

Frogs spawn on a deterministic cadence ``interval ± fuzzy%``; each frog lives
``persist`` seconds. The next spawn is pre-rolled *before* the current frog is
spawned so a crashed/failed spawn never kills the schedule (as v1 did).
"""

import logging
import random
import time
from asyncio import TimeoutError
from typing import Any

import discord
import pendulum

from cazzubot import templates, utils
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


async def on_frog_due(bot, payload: dict[str, Any]) -> None:
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

	if captured:
		# Reroll from the capture time for the next spawn.
		run_at = roll_future_frog(pendulum.now("UTC"), interval, fuzzy)
		await bot.scheduler.update_run_at(task_id, run_at)


async def spawn_and_wait(bot, persist: int, *, cid: int) -> bool:
	"""Spawn a frog in a channel and wait for someone to capture it."""
	channel = bot.get_channel(cid)
	if channel is None:
		_log.warning("frog channel %s not found; skipping", cid)
		return False

	timer_start = time.time()
	msg = await channel.send(FROG_EMOJI)
	await msg.add_reaction(FROG_NET_EMOJI)

	def check(reaction: discord.Reaction, user: discord.User) -> bool:
		return (
			reaction.message.id == msg.id
			and str(reaction.emoji) == FROG_NET_EMOJI
			and not user.bot
		)

	try:
		_, catcher = await bot.wait_for(
			"reaction_add", timeout=persist, check=check
		)
	except TimeoutError:
		return False

	timer_diff = time.time() - timer_start
	now = pendulum.now("UTC")
	uid = catcher.id

	await frog_db.add_capture_log(
		bot.db,
		uid,
		now,
		waited_for=timer_diff,
		frog_type=FrogTypeEnum.NORMAL,
	)
	await frog_db.modify_frog(
		bot.db, uid, modify=1, frog_type=FrogTypeEnum.NORMAL
	)
	await frog_db.modify_capture(bot.db, uid, modify=1)

	# send the capture message (user-configured template)
	msg_json = await frog_db.get_message(bot.settings) or {}
	frog_cnt_total = await frog_db.get_frogs(bot.db, uid)
	seasonal = await frog_db.seasonal_captures(
		bot.db, uid, now.year, (now.month - 1) // 3
	)

	utils.deep_map(
		msg_json,
		formatter,
		member=catcher,
		frog_cnt_old=frog_cnt_total - 1,
		frog_cnt_new=frog_cnt_total,
		seasonal_cap_old=seasonal - 1,
		seasonal_cap_new=seasonal,
	)
	content, embed, embeds = templates.prepare(msg_json)

	msg_caught = await channel.send("_ _", delete_after=7)
	if embed:
		await msg_caught.edit(content=content, embed=embed)
	elif embeds:
		await msg_caught.edit(content=content, embeds=embeds)

	try:
		await msg.delete()
	except discord.NotFound:
		pass
	return True


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


async def reset_frog_tasks(bot) -> None:
	"""Clear all frog tasks and re-queue from the spawn settings."""
	_log.info("resetting frog spawn tasks...")
	await bot.scheduler.drop_tag("frog")
	if not await frog_db.get_enabled(bot.settings):
		return
	await queue_frog_spawns(bot)


async def queue_frog_spawns(bot) -> None:
	"""Insert one task per configured spawn channel."""
	for spawn in await frog_db.get_spawns(bot.db):
		payload = dict(spawn)
		run_at = roll_future_frog(
			pendulum.now("UTC"), payload["interval"], payload["fuzzy"]
		)
		await bot.scheduler.add("frog", run_at, payload)
