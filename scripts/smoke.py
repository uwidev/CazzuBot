"""Boot smoke test — verifies the whole stack wires up without Discord.

Simulates a connected client (patches ``wait_until_ready``) so plugin loading,
schema application, scheduler registration and the command tree all run, then
tears down. Not a unit test suite; a "does it even boot" check.

Usage: .venv/bin/python scripts/smoke.py
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(
	0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from cazzubot import CazzuBot, Config  # noqa: E402


async def main() -> None:
	path = os.path.join(tempfile.mkdtemp(), "smoke.db")
	bot = CazzuBot(
		Config(token="fake-token", owner_id=1, guild_id=2, db_path=path)
	)

	# simulate a connected, ready client
	async def _ready() -> None:
		pass

	bot.wait_until_ready = _ready  # type: ignore[method-assign]

	await bot.setup_hook()
	try:
		print(f"plugins loaded: {[p.name for p in bot.plugins]}")
		print(f"prefix commands: {len(bot.commands)}")
		slashes = [c.qualified_name for c in bot.tree.get_commands()]
		print(f"app commands: {slashes}")
		for plugin in bot.plugins:
			names = sorted(
				c.name
				for c in bot.commands
				if c.cog_name
				and any(
					cog.__cog_name__ == c.cog_name for cog in plugin.cogs
				)
			)
			print(f"  {plugin.name}: {names}")

		# exercise the data layer end-to-end
		await bot.scheduler.add(
			"smoke", __import__("pendulum").now("UTC"), {"k": "v"}
		)
		assert await bot.scheduler.get("smoke"), "scheduler roundtrip"
		await bot.settings.set("smoke.key", [1, 2, 3])
		assert await bot.settings.get("smoke.key") == [1, 2, 3]
		print("data layer roundtrip OK")
	finally:
		await bot.close()

	print("SMOKE OK")


if __name__ == "__main__":
	asyncio.run(main())
