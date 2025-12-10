"""Custom bot class for type hinting and additional functionality."""

import logging
import os
import traceback

import discord
from asyncpg import Pool
from discord.ext import commands

from src import db
from src.json_handler import CustomDecoder, CustomEncoder

_log = logging.getLogger(__name__)


class CazzuBot(commands.Bot):
	def __init__(
		self,
		*args,
		pool: Pool,
		ext_path: str,
		is_debug: bool = False,
		debug_users: list[int] = [],
		**kwargs,
	):
		"""Assign the database pool, hotswap path, and database.

		Database should be a tuple of (name, host, user).
		Password is asked for at runtime. ???
		"""
		super().__init__(*args, **kwargs)
		self.pool: Pool = pool
		self.ext_path: str = ext_path
		self.is_debug: bool = is_debug
		self.debug_users: list[int] = debug_users
		self.is_sandbox: bool = kwargs["sandbox"]

		if self.is_debug:
			self.add_check(CazzuBot.is_dev_mode)

		db.member.init()
		db.user.init()
		db.guild.init()
		db.channel.init()

	@staticmethod
	async def is_dev_mode(ctx: commands.Context) -> bool:
		return await CazzuBot.is_owner(ctx.bot, ctx.author)

	async def on_ready(self):
		_log.info("Logged in as %s", self.user.name)

	async def on_command_error(
		self, ctx: commands.Context, err: commands.CommandError, /
	) -> None:
		if isinstance(err, commands.BadArgument):
			await ctx.reply(err)
			return
		if isinstance(err, discord.Forbidden):
			return

		await super().on_command_error(ctx, err)

	async def _load_extensions(self):
		for file in os.listdir(self.ext_path):
			if file.endswith(".py") and not file.startswith("sandbox"):
				try:
					await self.load_extension(
						f"{self.ext_path}.{file[:-3]}"
					)
					_log.info("|\t> loaded %s!", file[:-3])
				except (
					commands.ExtensionNotFound,
					commands.ExtensionAlreadyLoaded,
					commands.NoEntryPointError,
					commands.ExtensionFailed,
				):
					# _log.error(err)
					_log.error(traceback.format_exc())

	async def setup_hook(self) -> None:
		_log.info("Loading extensions...")
		if not self.is_sandbox:
			await self._load_extensions()
		else:
			await self._load_sandbox()

		_log.info("Loading json encoder and decoder...")
		self.json_encoder = CustomEncoder()
		self.json_decoder = CustomDecoder()

	async def _load_sandbox(self):
		try:
			await self.load_extension("ext.sandbox")
			_log.info("|\t> loaded sandbox!")
		except (
			commands.ExtensionNotFound,
			commands.ExtensionAlreadyLoaded,
			commands.NoEntryPointError,
			commands.ExtensionFailed,
		):
			# _log.error(err)
			_log.error(traceback.format_exc())

		# _log.info("Loading tasks...")
		# await task.all(bot.pool)

		# _log.info("Resolving tasks...")
		# _log.warning("Task resolution not yet implemented!")
