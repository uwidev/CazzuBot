"""User-configurable JSON message templates (port of v1's ``src/user_json.py``).

Admins can configure messages (level-ups, rank-ups, frog spawns, welcomes) as
JSON with ``{placeholder}`` tokens, validated against a jsonschema that mirrors
``discord.Embed``. ``verify`` checks + dry-runs a template; ``prepare`` turns a
stored dict into sendable content/embeds; ``send`` delivers one through any
send target.
"""

import copy
import json
import logging
from collections.abc import Callable
from typing import Any, cast

import discord
from discord.utils import MISSING
from jsonschema import ValidationError, validate

from cazzubot.errors import UserInputError

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
    Raises ``UserInputError`` on any parse/validation failure.
    """
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as err:
        raise UserInputError(f"Invalid JSON: {err}") from err

    if not isinstance(decoded, dict):
        raise UserInputError("Message must be a JSON object")
    message = cast(dict[str, Any], decoded)

    if formatter is not None:
        demo: dict[str, Any] = copy.deepcopy(message)
        from cazzubot.utils import deep_map

        deep_map(demo, formatter, **kwargs)
        try:
            validate(demo, MESSAGE_SCHEMA)
        except ValidationError as err:
            raise UserInputError(
                f"Invalid message template: {err.message}"
            ) from err
    return message


def prepare(
    message: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """Turn a stored message dict into ``(content, embed, embeds)``.

    Returns **plain JSON** — no framework objects — so service code can
    decide *whether* to send without touching discord. The conversion to
    a framework embed happens at the send edge (``embed_from_raw``).

    Falsy embed dicts (``{}``) are dropped like the old
    ``discord.Embed.from_dict`` filtering did — a valid embed that only
    sets color/timestamp is a non-empty dict and survives. A single embed
    wins over ``embeds``; a fully-empty message degrades to ``"_ _"``.
    """
    content = message.get("content")
    embed = message.get("embed") or None
    embeds = [e for e in message.get("embeds") or [] if e]
    if embed is not None:
        embeds = []  # a single embed wins over embeds (old if/elif order)
    if embed is None and not embeds:
        content = content or "_ _"  # API rejects fully-empty messages
    return content, embed, embeds


def embed_from_raw(raw: dict[str, Any]) -> discord.Embed:
    """Framework adapter: template JSON -> ``discord.Embed``.

    The only discord.py-touching step in this module; reimplemented for
    hikari's ``Embed`` on the swap.
    """
    return discord.Embed.from_dict(raw)


async def send(
    destination: Any,
    message: dict[str, Any],
    **kwargs: Any,
) -> Any:
    """Send a stored template message via ``destination.send(**kwargs)``.

    ``destination`` is any send target (a ``Messageable``, ``Context``, or
    webhook ``followup``); extra kwargs (``delete_after``, ``wait``, ...) are
    forwarded unchanged.
    """
    content, embed, embeds = prepare(message)
    return await destination.send(
        content=content,
        embed=embed_from_raw(embed) if embed is not None else MISSING,
        embeds=[embed_from_raw(e) for e in embeds] or MISSING,
        **kwargs,
    )
