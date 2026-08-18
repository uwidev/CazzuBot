"""Live component-payload smoke: send every shipped menu/modal to the sandbox.

Validates the layer the unit suite can't: whether Discord ACCEPTS the
component payloads the bot produces (the `components=` sequence protocol,
custom-emoji ids, modal rows). Each payload is posted to the sandbox guild
as a real message via REST — the exact ``_build_message_payload`` path the
bot uses — then deleted. Failures here are the bugs the fakes can't see.

Usage:
    GUILD_ID=408801760581386245 uv run python scripts/smoke_components.py
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any, cast

import hikari
import pendulum

from cazzubot import utils
from cazzubot.models import SpeciesKey
from dotenv import load_dotenv

load_dotenv(".env")

GUILD_ID = int(os.getenv("GUILD_ID", "408801760581386245"))
TOKEN = os.getenv("TOKEN_DEV", "")


def _payloads(client: hikari.api.RESTClient) -> list[tuple[str, object]]:
    """(label, components) for every menu the bot ships.

    The poll modal and its rules text display are intentionally absent:
    modal action rows (type 4) and text displays (type 10) are only valid
    in *modal responses*, not messages (verified: Discord rejects type 10
    in create_message) — create_modal_response consumes them via the same
    build()[0] path, which needs a real interaction to exercise live.
    """
    from plugins.experience.extension import TopMenu
    from plugins.frogs import factory

    confirm = utils.ConfirmMenu(author_id=1)
    top = TopMenu(
        cast(Any, client),
        cast(Any, SimpleNamespace(member=SimpleNamespace(id=1))),
        pendulum.datetime(2026, 1, 1),
        [(1, 1, 100)],
    )
    frog = factory.FrogCatchMenu(
        cast(Any, client), 99, SpeciesKey.LEAF_FROG
    )
    return [
        ("confirm", confirm),
        ("top", top),
        ("frog-catch", frog),
    ]


async def main() -> None:
    """Smoke-test the bot's components against the real API (CLI)."""
    app = hikari.RESTApp()
    await app.start()
    try:
        async with app.acquire(TOKEN, "Bot") as client:
            guild = await client.fetch_guild(GUILD_ID)
            channels = await client.fetch_guild_channels(GUILD_ID)
            text = next(
                (
                    c
                    for c in channels
                    if c.type == hikari.ChannelType.GUILD_TEXT
                ),
                None,
            )
            if text is None:
                print("no text channel in sandbox guild")
                return
            print(f"target: {guild.name} #{text.name} ({text.id})")
            for label, components in _payloads(client):
                try:
                    message = await client.create_message(
                        text.id,
                        content=f"_smoke_ {label}",
                        components=cast(Any, components),
                    )
                    await client.delete_message(text.id, message.id)
                    print(f"  OK  {label}")
                except hikari.HikariError as err:
                    print(f"  FAIL {label}: {err}")
    finally:
        await app.close()


if __name__ == "__main__":
    asyncio.run(main())
