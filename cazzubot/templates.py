"""User-configurable JSON message templates (port of v1's ``src/user_json.py``).

Admins can configure messages (level-ups, rank-ups, frog spawns, welcomes) as
JSON with ``{placeholder}`` tokens, validated against a jsonschema that mirrors
``discord.Embed``. ``verify`` checks + dry-runs a template; ``prepare`` turns a
stored dict into sendable content/embeds.
"""

import copy
import json
import logging
from collections.abc import Callable
from typing import Any, cast

import discord
from discord.ext import commands
from jsonschema import ValidationError, validate

_log = logging.getLogger(__name__)

EMBED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "url": {"type": "string", "format": "uri"},
        "timestamp": {"type": "string", "format": "date-time"},
        "color": {"type": "integer"},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "value"],
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                    "inline": {"type": "boolean"},
                },
            },
        },
        "author": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
        },
        "footer": {"type": "object"},
        "image": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
        },
        "thumbnail": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
        },
        "video": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
        },
        "provider": {"type": "object"},
    },
}

MESSAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "nonce": {"type": ["string", "number"]},
        "tts": {"type": "boolean"},
        "embed": EMBED_SCHEMA,
        "embeds": {"type": "array", "items": EMBED_SCHEMA},
        "allowed_mentions": {"type": "boolean"},
        "sticker_ids": {"type": "array", "items": {"type": "number"}},
        "attachments": {
            "type": "array",
            "maxContains": 0,  # reject attachments outright
        },
        "flags": {"type": "number"},
    },
    "additionalProperties": False,
}


def verify(
    raw: str,
    formatter: Callable[..., str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Parse + validate user-supplied message JSON.

    Pure CPU work (``json.loads`` + jsonschema validation) — deliberately
    sync; callers must not ``await`` it. Applies the formatter to a copy
    first so placeholder substitution is dry-run against the actual member.
    Raises ``commands.BadArgument`` on any parse/validation failure.
    """
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as err:
        raise commands.BadArgument(f"Invalid JSON: {err}") from err

    if not isinstance(decoded, dict):
        raise commands.BadArgument("Message must be a JSON object")
    message = cast(dict[str, Any], decoded)

    if formatter is not None:
        demo: dict[str, Any] = copy.deepcopy(message)
        from cazzubot.utils import deep_map

        deep_map(demo, formatter, **kwargs)
        try:
            validate(demo, MESSAGE_SCHEMA)
        except ValidationError as err:
            raise commands.BadArgument(
                f"Invalid message template: {err.message}"
            ) from err
    return message


def prepare(
    message: dict[str, Any],
) -> tuple[str | None, discord.Embed | None, list[discord.Embed]]:
    """Turn a stored message dict into ``(content, embed, embeds)``."""
    content = message.get("content")
    embed = embed_from_decoding(message)
    embeds = embeds_from_decoding(message)
    return content, embed, embeds


def embed_from_decoding(message: dict[str, Any]) -> discord.Embed | None:
    raw = message.get("embed")
    return discord.Embed.from_dict(raw) if raw else None


def embeds_from_decoding(message: dict[str, Any]) -> list[discord.Embed]:
    raws: list[dict[str, Any]] = message.get("embeds") or []
    return [discord.Embed.from_dict(raw) for raw in raws if raw]
