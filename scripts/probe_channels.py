"""Read-only probe: print guild channel tree + bot permissions.

Usage: uv run python scripts/probe_channels.py [--production] [--guild ID]
"""

from __future__ import annotations

import argparse
import asyncio

import discord

from cazzubot.config import Config


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--guild", type=int, default=None)
    args = parser.parse_args()

    config = Config.load(production=args.production)
    intents = discord.Intents.default()
    intents.members = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:  # pyright: ignore[reportUnusedFunction]
        guild_id = args.guild or config.guild_id
        guild = client.get_guild(guild_id)
        if guild is None:
            print(
                f"error: guild {guild_id} not found (token {'PROD' if args.production else 'DEV'})"
            )
            await client.close()
            return
        print(
            f"guild: {guild.name} ({guild.id})  bot={guild.me.name} ({guild.me.id})"
        )
        print(f"bot roles: {[r.name for r in guild.me.roles]}")
        gp = guild.me.guild_permissions
        print(
            f"guild perms: manage_channels={gp.manage_channels} "
            f"manage_roles={gp.manage_roles} manage_guild={gp.manage_guild}"
        )
        channels = await guild.fetch_channels()
        cats = [
            c for c in channels if isinstance(c, discord.CategoryChannel)
        ]
        top = [
            c
            for c in channels
            if c.category_id is None
            and not isinstance(c, discord.CategoryChannel)
        ]
        top.sort(key=lambda c: c.position)
        cats.sort(key=lambda c: c.position)
        print("\n-- uncategorized --")
        for c in top:
            print(f"  {c.position:>3} {c.name} ({c.__class__.__name__})")
        for cat in cats:
            print(f"[{cat.position:>3}] {cat.name}  (cat id {cat.id})")
            kids = [c for c in channels if c.category_id == cat.id]
            for c in sorted(
                kids, key=lambda c: (c.__class__.__name__, c.position)
            ):
                print(
                    f"    {c.position:>3} {c.name} ({c.__class__.__name__})"
                )
        # bot perms on the boundary region
        activities = next(
            (c for c in cats if c.name == "Activities"), None
        )
        if activities is not None:
            perms = activities.permissions_for(guild.me)
            print(
                f"\nbot perms on 'Activities': manage_channels={perms.manage_channels} view={perms.view_channel}"
            )
        await client.close()

    await client.start(config.token)


if __name__ == "__main__":
    asyncio.run(main())
