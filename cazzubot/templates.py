"""User-configurable JSON message templates (port of v1's ``src/user_json.py``).

Admins can configure messages (level-ups, rank-ups, frog spawns, welcomes) as
JSON with ``{placeholder}`` tokens, validated against a jsonschema that mirrors
Discord's embed payload. ``verify`` checks + dry-runs a template;
``prepare`` turns a stored dict into sendable content/embeds; ``send``
delivers one through any send target.

Depended on by: ``levels``/``ranks`` presenters, ``frogs`` (configured spawn
and capture messages) and ``welcome``.
"""

import copy
import json
import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

import hikari
import lightbulb
from hikari.undefined import UNDEFINED
from jsonschema import ValidationError, validate

from cazzubot.errors import UserInputError
from cazzubot.utils import deep_map, schedule_delete, text_channel

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

# mention patterns scanned in rendered message text (content + embeds) to
# derive the least-permissive user/role mention lists
_USER_MENTION = re.compile(r"<@!?(\d+)>")
_ROLE_MENTION = re.compile(r"<@&(\d+)>")


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


def build_payload(message: dict[str, Any]) -> dict[str, Any]:
    """The send payload for a prepared template (UNDEFINED for unset keys).

    Shared by :func:`send` (context/channel targets) and the frogs factory,
    which must send via ``rest.create_message`` directly.
    """
    content, embed, embeds = prepare(message)
    return dict(
        content=content if content is not None else UNDEFINED,
        embed=embed_from_raw(embed) if embed is not None else UNDEFINED,
        embeds=[embed_from_raw(e) for e in embeds] or UNDEFINED,
    )


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

    Mention policy is least-permissive: only the users/roles actually
    written as ``<@id>`` / ``<@&id>`` in the rendered message — content or
    any embed text field — get parse rights, never a blanket "all users"
    or "all roles". ``allowed_mentions: true`` additionally allows
    ``@everyone``/``@here`` when present; ``false`` parses nothing.
    Caller-supplied mention kwargs win over the template-derived values.
    """
    content, embed, embeds = prepare(message)
    allowed = message.get("allowed_mentions")
    if allowed is not False:
        user_ids, role_ids, everyone = _extract_mentions(
            content, [embed] if embed else list(embeds)
        )
        kwargs.setdefault(
            "user_mentions", user_ids if user_ids else hikari.UNDEFINED
        )
        kwargs.setdefault(
            "role_mentions", role_ids if role_ids else hikari.UNDEFINED
        )
        kwargs.setdefault(
            "mentions_everyone",
            True if (allowed is True and everyone) else hikari.UNDEFINED,
        )
    payload = build_payload(message)
    if isinstance(destination, lightbulb.Context):
        # hikari channels have ``send``; lightbulb contexts have ``respond``
        return await destination.respond(**payload, **kwargs)
    return await destination.send(**payload, **kwargs)


async def send_to_channel(
    bot: Any,
    channel_id: int | None,
    message: dict[str, Any],
    *,
    delete_after: float = 0,
) -> bool:
    """Send a template to a guild channel; ``False`` when it can't send.

    The shared "send and optionally clean up" tail of the level-up /
    rank-up presenters: resolve the cached channel, deliver, and schedule
    the deletion. ``bot`` is only used for the channel cache and the
    delete timer — the destination itself stays framework-agnostic.
    """
    channel = text_channel(bot, channel_id)
    if channel is None:
        return False
    sent = await send(channel, message)
    if delete_after:
        schedule_delete(bot, channel.id, sent.id, delete_after)
    return True


def _extract_mentions(
    content: str | None,
    embeds: list[dict[str, Any]],
) -> tuple[list[int], list[int], bool]:
    """The explicitly-mentioned user/role ids in a rendered message.

    Least-permissive mention source: only users/roles written as ``<@id>``
    / ``<@&id>`` in the message (content + every embed string field) get
    parse rights. Returns ``(user_ids, role_ids, everyone)`` — ``everyone``
    is True when ``@everyone``/``@here`` appears in the text.
    """
    user_ids: list[int] = []
    role_ids: list[int] = []
    everyone = False
    for text in _text_parts(content, embeds):
        user_ids.extend(int(uid) for uid in _USER_MENTION.findall(text))
        role_ids.extend(int(rid) for rid in _ROLE_MENTION.findall(text))
        if "@everyone" in text or "@here" in text:
            everyone = True
    return (
        list(dict.fromkeys(user_ids)),
        list(dict.fromkeys(role_ids)),
        everyone,
    )


def _text_parts(
    content: str | None, embeds: list[dict[str, Any]]
) -> list[str]:
    """Every user-visible message string (content + embed text) as a list."""
    parts = [content] if content else []
    for embed in embeds:
        for key in ("title", "description"):
            value = embed.get(key)
            if isinstance(value, str):
                parts.append(value)
        author = embed.get("author") or {}
        if isinstance(author.get("name"), str):
            parts.append(author["name"])
        footer = embed.get("footer") or {}
        if isinstance(footer.get("text"), str):
            parts.append(footer["text"])
        for field in embed.get("fields") or []:
            for key in ("name", "value"):
                value = field.get(key)
                if isinstance(value, str):
                    parts.append(value)
    return parts
