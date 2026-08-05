"""General-purpose helpers shared by plugins."""

import logging
from collections.abc import Callable
from typing import Any, NamedTuple, TypeVar

import discord
import pendulum
from discord.ext import commands

_log = logging.getLogger(__name__)

T = TypeVar("T")


class OldNew(NamedTuple):
	"""Pair of (old, new) values, e.g. level or rank before/after a message."""

	old: Any
	new: Any


def month2season(month: int) -> int:
	"""Bucket a calendar month (1-12) into a season (0-3).

	Matches v1: months are zero-indexed then floordiv 3, so
	Jan-Mar -> 0, Apr-Jun -> 1, Jul-Sep -> 2, Oct-Dec -> 3.
	"""
	return (month - 1) // 3


def season_start(year: int, season: int) -> pendulum.DateTime:
	"""First instant of a season (Jan/Apr/Jul/Oct 1st, UTC)."""
	if not 0 <= season <= 3:
		raise ValueError("Seasons must be in the range of 0-3")
	return pendulum.datetime(year, 1 + 3 * season, 1, tz="UTC")


def season_end(year: int, season: int) -> pendulum.DateTime:
	"""First instant after a season (exclusive upper bound)."""
	return season_start(year, season).add(months=3)


def ordinal(n: int) -> str:
	"""1st, 2nd, 3rd, 4th, …"""
	if 10 <= n % 100 <= 20:
		suffix = "th"
	else:
		suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
	return f"{n}{suffix}"


def calc_percentile(rank: int, total: int) -> float:
	"""Percentile of a rank within a total (1 is best)."""
	return (total - rank + 1) / total * 100 if total else 0.0


def prepare_embed(
	title: str | None = None,
	description: str | None = None,
	*,
	color: int = 0x9EDBF7,
) -> discord.Embed:
	"""Standard embed with the -sarono footer."""
	embed = discord.Embed(
		title=title, description=description, color=color
	)
	embed.set_footer(
		text="-sarono",
		icon_url="https://files.catbox.moe/3cy0by.webp",
	)
	return embed


async def find_user(
	bot: commands.Bot, ctx: commands.Context, uid: int
) -> discord.User | discord.Member | None:
	"""Resolve a user id from member cache, user cache, or a fetch."""
	for guild in bot.guilds:
		member = guild.get_member(uid)
		if member:
			return member
	user = bot.get_user(uid)
	if user:
		return user
	try:
		return await bot.fetch_user(uid)
	except discord.NotFound:
		return None


async def author_confirm(
	ctx: commands.Context,
	confirmation_msg: str = "Please confirm.",
	*,
	delete_after: bool = True,
) -> bool:
	"""Ask the author for a 👍/❌ confirmation; True if 👍."""
	if ctx.invoked_with == "help":
		return True
	confirm = await ctx.send(confirmation_msg)
	await confirm.add_reaction("👍")
	await confirm.add_reaction("❌")

	def check(reaction, user):
		return (
			user == ctx.author
			and str(reaction.emoji) in ("👍", "❌")
			and reaction.message.id == confirm.id
		)

	try:
		reaction, _ = await ctx.bot.wait_for(
			"reaction_add", timeout=7.0, check=check
		)
	except TimeoutError:
		await confirm.delete()
		return False

	if delete_after:
		await confirm.delete()
	return str(reaction.emoji) == "👍"


def deep_map(
	value: Any, formatter: Callable[..., str], **kwargs: Any
) -> Any:
	"""In-place walk over dicts/lists applying ``formatter`` to every string."""
	if isinstance(value, dict):
		for k, v in value.items():
			value[k] = deep_map(v, formatter, **kwargs)
		return value
	if isinstance(value, list):
		for i, v in enumerate(value):
			value[i] = deep_map(v, formatter, **kwargs)
		return value
	if isinstance(value, str):
		return formatter(value, **kwargs)
	return value


def split_duration_and_text(raw: str) -> tuple[str, str]:
	"""Split a leading time token from the rest of a string.

	Used by ``mute``/``ban``: "2h because i said so" -> ("2h", "because…").
	Returns ``(raw, "")`` when no leading duration parses.
	"""
	from cazzubot.timeparse import InvalidTimeError, parse_duration

	first = raw.split(maxsplit=1)
	try:
		parse_duration(first[0])
	except (InvalidTimeError, ValueError, IndexError):
		return raw, ""
	return first[0], first[1] if len(first) > 1 else ""
