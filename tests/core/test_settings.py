"""JSON key-value settings store — ported from scripts/functest.py."""

from __future__ import annotations

from cazzubot.bot import CazzuBot


async def test_settings_json_roundtrip(bot: CazzuBot) -> None:
    await bot.settings.set("welcome.message", {"content": "hi {name}"})
    assert (await bot.settings.get("welcome.message"))[
        "content"
    ] == "hi {name}"
