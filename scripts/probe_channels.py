"""Read-only probe: print guild channel tree + bot permissions.

Usage: uv run python scripts/probe_channels.py [--production] [--guild ID]
"""

from __future__ import annotations

import argparse
import asyncio

import hikari

from cazzubot.config import Config


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--guild", type=int, default=None)
    args = parser.parse_args()

    config = Config.load(production=args.production)
    app = hikari.RESTApp()
    await app.start()
    try:
        async with app.acquire(config.token, "Bot") as client:
            guild_id = args.guild or config.guild_id
            try:
                guild = await client.fetch_guild(guild_id)
            except hikari.NotFoundError:
                print(
                    f"error: guild {guild_id} not found (token {'PROD' if args.production else 'DEV'})"
                )
                return
            me = await client.fetch_my_user()
            member = await client.fetch_member(guild_id, me.id)
            print(
                f"guild: {guild.name} ({guild.id})  bot={member.display_name} ({member.id})"
            )
            roles = {r.id: r for r in await client.fetch_roles(guild_id)}
            print(
                f"bot roles: {[roles[r].name for r in member.role_ids if r in roles]}"
            )
            perms = hikari.Permissions.NONE
            for rid in member.role_ids:
                if rid in roles:
                    perms |= roles[rid].permissions
            print(
                f"guild perms: manage_channels={bool(perms & hikari.Permissions.MANAGE_CHANNELS)} "
                f"manage_roles={bool(perms & hikari.Permissions.MANAGE_ROLES)} "
                f"manage_guild={bool(perms & hikari.Permissions.MANAGE_GUILD)}"
            )
            channels = await client.fetch_guild_channels(guild_id)
            cats = [
                c
                for c in channels
                if c.type == hikari.ChannelType.GUILD_CATEGORY
            ]
            top = [
                c
                for c in channels
                if c.parent_id is None
                and c.type != hikari.ChannelType.GUILD_CATEGORY
            ]
            top.sort(key=lambda c: getattr(c, "position", 0))
            cats.sort(key=lambda c: getattr(c, "position", 0))
            print("\n-- uncategorized --")
            for c in top:
                print(
                    f"  {getattr(c, 'position', 0):>3} {c.name} ({type(c).__name__})"
                )
            for cat in cats:
                print(
                    f"[{getattr(cat, 'position', 0):>3}] {cat.name}  (cat id {cat.id})"
                )
                kids = [c for c in channels if c.parent_id == cat.id]
                for c in sorted(
                    kids,
                    key=lambda c: (
                        type(c).__name__,
                        getattr(c, "position", 0),
                    ),
                ):
                    print(
                        f"    {getattr(c, 'position', 0):>3} {c.name} ({type(c).__name__})"
                    )
    finally:
        await app.close()


if __name__ == "__main__":
    asyncio.run(main())
