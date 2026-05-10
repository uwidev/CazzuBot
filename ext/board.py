"""Weekly spotlight of images posted in a channel.

Scrapes attachments from messages for that week. Then stitches said images into
a single image with labels for each image. Then does voting logic from user
votes to determine the image with the most vote.
"""

# TODO: bot logic to interact with the database
# TODO: poll summary
# TODO: poll timer
# TODO: allow end vote early
# TODO: poll create command

# TODO: programatically create a message that links vote image to original message for source

import logging
from pathlib import Path

import pendulum
from discord.ext import commands
from pendulum import DateTime

_log = logging.getLogger(__name__)


class Board(commands.Cog):
	def __init__(self, bot):
		self.bot = bot

	@commands.group()
	async def board(self, ctx: commands.Context):
		"""Group for board"""

	@board.command(name="scrape")
	async def board_scrape(self, ctx: commands.Context, week: int = -1):
		"""Give a week (number), scrape all images for that week.

		For now, assume it is this year.
		"""
		if week <= 0:
			week = pendulum.now().week_of_year

		year = pendulum.now().year

		start, end = get_week_bounds(year, week)

		_log.info(f"{start}")
		_log.info(f"{end}")

		ch = ctx.channel
		id = 0
		log_path = Path(f"./board/{year}-W{week:02}.txt")
		if not log_path.exists():
			with log_path.open("x") as fp:
				fp.write("id\tfilename\tuser id\tmsg id\n")
		with log_path.open("a") as fp:
			async for message in ch.history(
				after=start, before=end, limit=None
			):
				for attachment in message.attachments:
					if (
						attachment.content_type
						and attachment.content_type.startswith("image/")
					):
						filename = Path(
							f"./board/{id}-{attachment.filename}"
						)
						await attachment.save(filename)
						_log.info(f"saved {filename}")
						fp.write(
							f"{id}\t{attachment.filename}\t{message.author.id}\t{message.id}\n"
						)
						id += 1

		_log.info("done scraping images for this week")


def get_week_bounds(year, week_number) -> tuple[DateTime, DateTime]:
	"""
	Generated using DeepSeek
	"""
	# Pendulum weeks start on Monday by default
	date: DateTime = pendulum.parse(f"{year}-W{week_number:02}")

	# Get the start of the target week
	start_date = date.start_of("week")
	end_date = date.end_of("week")

	return start_date, end_date


async def setup(bot: commands.Bot):
	await bot.add_cog(Board(bot))
