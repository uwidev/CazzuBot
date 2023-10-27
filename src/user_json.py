"""Deals with handlings of user input custom JSON."""

import copy
import json
import logging
from collections.abc import Callable

import discord
import pendulum
from discord.ext import commands
from jsonschema import ValidationError, validate

from src import utility


_log = logging.getLogger(__name__)


EMBED_SCHEMA = {
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
                "properties": {"name": {"type": "string"}, "value": {"type": "string"}},
                "required": ["name", "value"],
            },
        },
        "author": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "url": {"type": "string", "format": "uri"},
                "icon_url": {"type": "string", "format": "uri"},
            },
        },
        "footer": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "icon_url": {"type": "string", "format": "uri"},
            },
        },
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
            "properties": {
                "url": {"type": "string", "format": "uri"},
                "proxy_url": {"type": "string", "format": "uri"},
                "height": {"type": "integer"},
                "width": {"type": "integer"},
            },
            "required": ["url"],
        },
        "provider": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "url": {"type": "string", "format": "uri"},
            },
        },
    },
}

MESSAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "nonce": {"type": ["string", "number"]},
        "tts": {"type": "boolean"},
        "embed": EMBED_SCHEMA,
        "embeds": {"type": "array", "items": EMBED_SCHEMA},
        "allowed_mentions": {"type": "boolean"},
        "sticker_ids": {"type": "array", "items": {"type": "number"}},
        "attachments": {"type": "array", "maxContains": 0},  # Do not accept attachments
        "flags": {"type": "number"},
    },
    "additionalProperties": False,
}


async def verify(
    bot,
    ctx: commands.Context,
    message: str,
    formatter: Callable = None,
    **kwarg,
):
    """Verify if a user's provided json argument is valid.

    Return its decoded dict if valid, None if not.

    If formatter is given, it will call that formatter and pass all kwargs to it. This
    formatter will be called on all str objects in the json. The returned dict is
    the pre-formatted version.
    """
    decoded = None
    try:
        decoded: dict = bot.json_decoder.decode(message)  # decode to verify valid json

        fix_timestamps(decoded)

        # send embed to verify valid embed
        demo = copy.deepcopy(decoded)

        if formatter:
            utility.deep_map(demo, formatter, **kwarg)

        # We use jsonschema to make sure people aren't abusing the bot to store
        # excess information. Still not 100% safe, but still better than just checking
        # to see if the embed has the fields to be sendable.
        validate(demo, MESSAGE_SCHEMA)

        # This is another way to validate. If we get a HTTP error (can't remember which
        # one), we know the embed is invalid.
        # content, embed, embeds = prepare_message(demo)
        # await ctx.reply(
        #     content=content,
        #     embed=embed,
        #     embeds=embeds,
        # )

    except json.decoder.JSONDecodeError as err:
        msg = f"Provided JSON is not a valid JSON object.\n\n{err.msg}"
        raise commands.BadArgument(msg) from err

    except ValidationError as err:
        msg = f"Provided JSON is not a valid Discord message.\n\n{err.message}"
        raise commands.BadArgument(msg) from err

    else:
        return decoded


def fix_timestamps(embed: dict):
    """Convert key timestamp to isoformat for database."""
    timestamp = embed.get("timestamp", None)
    if timestamp:
        embed["timestamp"] = pendulum.parser.parse(timestamp).isoformat()


def prepare(embed_json: dict) -> tuple[str, dict, list]:
    """Parse dictionary to embed objects, return as tuple for sending message."""
    content = embed_json.get("content", None)
    embed = embed_from_decoding(embed_json)
    embeds = embeds_from_decoding(embed_json)

    return content, embed, embeds


def embed_from_decoding(d: dict):
    """Return an embed object from json.

    None if doesn't exist.
    """
    embed = d.get("embed", None)
    if not embed:
        return None

    return discord.Embed.from_dict(embed)


def embeds_from_decoding(d: dict):
    """Return a list of embed objects from a json.

    None if empty.
    """
    embeds = d.get("embeds", None)
    if not embeds:
        return None

    return [discord.Embed.from_dict(embed) for embed in embeds]
