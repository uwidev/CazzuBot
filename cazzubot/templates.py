"""User-configurable JSON message templates (port of v1's ``src/user_json.py``).

Admins can configure messages (level-ups, rank-ups, frog spawns, welcomes) as
JSON with ``{placeholder}`` tokens, validated against a jsonschema that mirrors
Discord's embed payload. ``verify`` checks + dry-runs a template;
``prepare`` turns a stored dict into sendable content/embeds; ``send``
delivers one through any send target.
"""

import copy
import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

import hikari
import lightbulb
from hikari.undefined import UNDEFINED
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
    formatter: Callable[..., str],
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


def embed_from_raw(raw: dict[str, Any]) -> hikari.Embed:
    """Framework adapter: template JSON -> ``hikari.Embed``.

    The only hikari-touching step in this module; reimplemented from
    ``discord.Embed.from_dict`` semantics (empty-name author/footer, plain
    int color, ISO timestamp). ``video``/``provider`` are received-only
    embed fields the create-message API cannot set — admitted by the
    schema for forward compatibility, ignored here.
    """
    embed = hikari.Embed(
        title=raw.get("title"),
        description=raw.get("description"),
        url=raw.get("url"),
        color=raw.get("color"),
    )
    timestamp = raw.get("timestamp")
    if timestamp:
        embed.timestamp = datetime.fromisoformat(timestamp)
    for field in raw.get("fields") or []:
        embed.add_field(
            name=field["name"],
            value=field["value"],
            inline=bool(field.get("inline")),
        )
    author = raw.get("author") or {}
    if author:
        embed.set_author(
            name=author.get("name") or "", url=author.get("url")
        )
    footer = raw.get("footer") or {}
    if footer:
        embed.set_footer(text=footer.get("text") or "")
    image = raw.get("image") or {}
    if image:
        embed.set_image(image.get("url"))
    thumbnail = raw.get("thumbnail") or {}
    if thumbnail:
        embed.set_thumbnail(thumbnail.get("url"))
    return embed


async def send(
    destination: Any,
    message: dict[str, Any],
    **kwargs: Any,
) -> Any:
    """Send a stored template message to a channel or command context.

    ``destination`` is any send target: a hikari ``TextableChannel`` (uses
    ``send``), a lightbulb ``Context`` (uses ``respond`` — it has no
    ``send``), or a fake; extra kwargs are forwarded unchanged where the
    target supports them. Unset payload keys go out as
    ``hikari.undefined.UNDEFINED`` (omitted), never ``None``.

    Mention parsing follows the template's ``allowed_mentions`` flag:
    absent → users + roles are parsed (``@everyone``/``@here`` never),
    ``true`` → everything, ``false`` → nothing. Caller-supplied mention
    kwargs win over the template default.
    """
    content, embed, embeds = prepare(message)
    payload = dict(
        content=content if content is not None else UNDEFINED,
        embed=embed_from_raw(embed) if embed is not None else UNDEFINED,
        embeds=[embed_from_raw(e) for e in embeds] or UNDEFINED,
    )
    for key, value in _mention_kwargs(
        message.get("allowed_mentions")
    ).items():
        kwargs.setdefault(key, value)
    if isinstance(destination, lightbulb.Context):
        # hikari channels have ``send``; lightbulb contexts have ``respond``
        return await destination.respond(**payload, **kwargs)
    return await destination.send(**payload, **kwargs)


def _mention_kwargs(allowed: bool | None) -> dict[str, bool]:
    """Map a template's ``allowed_mentions`` flag to hikari mention kwargs.

    absent → parse users + roles (Discord's platform default minus
    ``@everyone``); ``true`` → also parse ``@everyone``/``@here``;
    ``false`` → parse nothing (hikari's no-mentions default). Discord
    validates mention presence server-side, so phantom pings can't occur.
    """
    if allowed is False:
        return {}
    kwargs = {"user_mentions": True, "role_mentions": True}
    if allowed is True:
        kwargs["mentions_everyone"] = True
    return kwargs
