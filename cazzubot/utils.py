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


class ConfirmView(discord.ui.View):
	"""Yes/No button prompt; ``value`` is True / False / None (timed out).

	Only the invoking author's clicks count. On an answer the message is
	deleted when ``delete_after`` is set (mirroring the old reaction-based
	flow), otherwise the buttons are stripped from it.
	"""

	def __init__(
		self,
		author_id: int,
		*,
		timeout: float = 7.0,
		delete_after: bool = True,
	) -> None:
		super().__init__(timeout=timeout)
		self.author_id = author_id
		self.delete_after = delete_after
		self.value: bool | None = None

	async def _finish(
		self, interaction: discord.Interaction, value: bool
	) -> None:
		if interaction.user.id != self.author_id:
			return  # other users' clicks are ignored
		self.value = value
		self.stop()
		if self.delete_after and interaction.message is not None:
			await interaction.response.defer()
			try:
				await interaction.message.delete()
			except discord.NotFound:
				pass
		else:
			await interaction.response.edit_message(view=None)

	@discord.ui.button(
		label="Yes", style=discord.ButtonStyle.success, emoji="👍"
	)
	async def yes(
		self, interaction: discord.Interaction, button: discord.ui.Button
	) -> None:
		await self._finish(interaction, True)

	@discord.ui.button(
		label="No", style=discord.ButtonStyle.danger, emoji="❌"
	)
	async def no(
		self, interaction: discord.Interaction, button: discord.ui.Button
	) -> None:
		await self._finish(interaction, False)


async def author_confirm(
	ctx: commands.Context,
	confirmation_msg: str = "Please confirm.",
	*,
	delete_after: bool = True,
) -> bool:
	"""Ask the author to confirm with Yes/No buttons; True if Yes."""
	if ctx.invoked_with == "help":
		return True
	view = ConfirmView(ctx.author.id, delete_after=delete_after)
	confirm = await ctx.send(confirmation_msg, view=view)
	await view.wait()
	if (
		view.value is None
	):  # timed out — mirror old behaviour: remove prompt
		try:
			await confirm.delete()
		except discord.NotFound:
			pass
		return False
	return view.value


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
