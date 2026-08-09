"""Offline interaction driver — exercise the bot's real event pipeline.

A "press" here is a synthetic gateway interaction fed through hikari's own
deserializer and event manager, so every layer a real Discord click passes
through runs for real: raw ``InteractionCreateEvent`` listeners (counter,
poll), lightbulb's menu lookup by ``custom_id``, ``MenuContext``/``ModalContext``
construction, the command pipeline (option solving, checks, error handler),
and the response lifecycle — with ``FakeRest`` standing in for Discord's
interaction-webhook endpoints (see ``tests.fakes.FakeRest``).

What is NOT exercised: the network, Discord's payload validation, rate
limits, and real gateway/cache events. Those stay in the live sandbox suite.

Usage::

    result = await run_slash(bot, "frog spawn", user_id=1)
    result = await press_button(bot, custom_id="counter:baka", message_id=1001)
    result = await submit_modal(bot, custom_id="poll:submit:1", values={...})

Each call awaits every listener under a 3-second budget (Discord's response
window) and returns a :class:`PressResult` with everything the fake REST
recorded during the dispatch, plus any handler exceptions.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import hikari

from tests.fakes import rest_of

# Discord gives an interaction 3s to produce an initial response; the
# driver enforces the same budget so "didn't respond in time" bugs fail
# the test instead of hanging it.
RESPONSE_BUDGET = 3.0

# Arbitrary but stable snowflakes for the synthetic interactions.
_APP_ID = 1111111111111111111
_IDS = itertools.count(900000000000000000)
_TOKENS = itertools.count(1)
_SHARD = SimpleNamespace(id=0)


@dataclass
class PressResult:
    """Everything the fake REST recorded during one dispatch."""

    token: str
    responses: list[tuple[hikari.ResponseType, dict[str, Any]]] = field(
        default_factory=list
    )
    edits: list[tuple[int | str, dict[str, Any]]] = field(
        default_factory=list
    )
    deletes: list[int | str] = field(default_factory=list)
    followups: list[dict[str, Any]] = field(default_factory=list)
    modals: list[dict[str, Any]] = field(default_factory=list)
    exceptions: list[BaseException] = field(default_factory=list)
    message_ids: list[int] = field(default_factory=list)

    @property
    def responded(self) -> bool:
        """True when the interaction got an initial response."""
        return bool(self.responses)

    @property
    def response_type(self) -> hikari.ResponseType | None:
        return self.responses[0][0] if self.responses else None

    @property
    def first_response(self) -> dict[str, Any] | None:
        """The initial response payload (content/flags/embed/components)."""
        return self.responses[0][1] if self.responses else None

    @property
    def response_message_id(self) -> int | None:
        """The message id Discord would assign to the initial response."""
        return self.message_ids[0] if self.message_ids else None


# -- driver entry points --------------------------------------------------


async def press_button(
    bot: Any,
    *,
    custom_id: str,
    message_id: int,
    user_id: int,
    username: str = "tester",
    channel_id: int = 99,
    guild_id: int = 2,
    member_permissions: int = 8,
    timeout: float = RESPONSE_BUDGET,
) -> PressResult:
    """Simulate a button press (component interaction, type 3)."""
    token = _token()
    user = _user_payload(user_id, username)
    payload = _base_payload(
        type_=3,
        token=token,
        user=user,
        channel_id=channel_id,
        guild_id=guild_id,
        member_permissions=member_permissions,
        data={
            "custom_id": custom_id,
            "component_type": 2,
        },
        message=_message_payload(message_id, channel_id, user),
    )
    return await _dispatch(bot, payload, token=token, timeout=timeout)


async def run_slash(
    bot: Any,
    path: str,
    *,
    options: dict[str, Any] | None = None,
    resolved: dict[str, dict[str, Any]] | None = None,
    user_id: int,
    username: str = "tester",
    channel_id: int = 99,
    guild_id: int = 2,
    member_permissions: int = 8,
    timeout: float = RESPONSE_BUDGET,
) -> PressResult:
    """Invoke a slash command through lightbulb's real command pipeline.

    ``path`` is the space-separated command path, e.g. ``"frog set
    enabled"``. ``options`` maps leaf option names to JSON-native values
    (str/int/bool/float); values that appear in ``resolved`` (channels/
    members/roles) are sent as their snowflake with the resolved data
    attached, like Discord does.
    """
    parts = path.split()
    data: dict[str, Any] = {
        "id": str(next(_IDS)),
        "name": parts[0],
        "type": 1,
        "guild_id": str(guild_id),
    }
    leaf = [
        _option_payload(name, value, resolved or {})
        for name, value in (options or {}).items()
    ]
    node: dict[str, Any] = {"name": parts[-1], "type": 1, "options": leaf}
    for name in reversed(parts[1:-1]):
        node = {"name": name, "type": 2, "options": [node]}
    if parts[1:]:
        data["options"] = [node]
    else:
        data["options"] = leaf
    if resolved:
        data["resolved"] = resolved

    token = _token()
    payload = _base_payload(
        type_=2,
        token=token,
        user=_user_payload(user_id, username),
        channel_id=channel_id,
        guild_id=guild_id,
        member_permissions=member_permissions,
        data=data,
    )
    return await _dispatch(bot, payload, token=token, timeout=timeout)


async def submit_modal(
    bot: Any,
    *,
    custom_id: str,
    values: dict[str, str],
    user_id: int,
    username: str = "tester",
    channel_id: int = 99,
    guild_id: int = 2,
    member_permissions: int = 8,
    timeout: float = RESPONSE_BUDGET,
) -> PressResult:
    """Submit a modal (modal interaction, type 5)."""
    token = _token()
    payload = _base_payload(
        type_=5,
        token=token,
        user=_user_payload(user_id, username),
        channel_id=channel_id,
        guild_id=guild_id,
        member_permissions=member_permissions,
        data={
            "custom_id": custom_id,
            "components": [
                {
                    "type": 1,
                    "id": str(next(_IDS)),
                    "components": [
                        {
                            "type": 4,
                            "id": str(next(_IDS)),
                            "custom_id": cid,
                            "value": value,
                        }
                        for cid, value in values.items()
                    ],
                }
            ],
        },
    )
    return await _dispatch(bot, payload, token=token, timeout=timeout)


async def wait_for_menu(
    bot: Any, *, timeout: float = 3.0
) -> dict[str, str]:
    """Wait until a lightbulb menu is attached; return label/emoji → id.

    Buttons created by ``add_interactive_button`` get random custom ids
    (``lb_<uuid>``), so tests discover them from the attached menu the way
    a user sees them: by label (``Yes``/``No``) or emoji (``▶``/``◀``).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        buttons = attached_buttons(bot)
        if buttons:
            return buttons
        await asyncio.sleep(0.01)
    raise TimeoutError("no menu was attached within the timeout")


async def wait_for_modal(
    bot: Any, custom_id: str, *, timeout: float = 3.0
) -> None:
    """Wait until a lightbulb modal with ``custom_id`` is attached."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if custom_id in bot.lightbulb._attached_modals:  # pyright: ignore[reportPrivateUsage]
            return
        await asyncio.sleep(0.01)
    raise TimeoutError(f"modal {custom_id!r} was not attached")


def attached_buttons(bot: Any) -> dict[str, str]:
    """label/emoji → custom_id for every button on attached menus."""
    buttons: dict[str, str] = {}
    for container in bot.lightbulb._attached_menus:  # pyright: ignore[reportPrivateUsage]
        for custom_id, component in container.custom_ids.items():
            label = (
                getattr(component, "label", None)
                or getattr(component, "emoji", None)
                or custom_id
            )
            buttons[str(label)] = custom_id
    return buttons


def modal_input_custom_id(modal: Any) -> str:
    """custom_id of a Modal's first text input (uuid-generated)."""
    from hikari.impl.special_endpoints import TextInputBuilder

    for row in modal:
        for component in row.components:
            if isinstance(component, TextInputBuilder):
                return component.custom_id
    raise ValueError("modal has no text input")


# -- helpers --------------------------------------------------------------


async def _drain_exceptions(
    queue: asyncio.Queue[BaseException],
) -> list[BaseException]:
    """Collect exceptions from the fire-and-forget ExceptionEvent tasks.

    hikari re-dispatches listener failures as ``ExceptionEvent`` in a
    separate task; the capture callback lands one loop tick later. Drain
    until the queue stays empty for a grace period, so a failure that
    lands between passes is still caught.
    """
    exceptions: list[BaseException] = []
    empty_since: float | None = None
    grace = 0.05  # generous vs the one-loop-tick dispatch delay
    while True:
        await asyncio.sleep(0.01)
        if queue.empty():
            if empty_since is None:
                empty_since = asyncio.get_running_loop().time()
            elif asyncio.get_running_loop().time() - empty_since >= grace:
                return exceptions
            continue
        empty_since = None
        while True:
            try:
                exceptions.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break


async def _dispatch(
    bot: Any, payload: dict[str, Any], *, token: str, timeout: float
) -> PressResult:
    """Deserialize the payload and run every listener to completion."""
    event = bot.event_factory.deserialize_interaction_create_event(
        _SHARD, payload
    )
    rest = rest_of(bot)
    if (message := payload.get("message")) is not None:
        # Discord lets a click's webhook manage the message its button
        # lives on once acked — model that scoped exception
        rest.register_source_message(token, int(message["id"]))
    snapshot = {
        key: list(entries) for key, entries in rest.interaction_log.items()
    }
    message_snapshot = {t: m.id for t, m in rest.webhook_messages.items()}
    queue: asyncio.Queue[BaseException] = asyncio.Queue()

    async def _capture(
        err_event: hikari.ExceptionEvent[Any],
    ) -> None:
        queue.put_nowait(err_event.exception)

    bot.event_manager.subscribe(hikari.ExceptionEvent, _capture)
    try:
        future = bot.event_manager.dispatch(event, return_tasks=True)
        await asyncio.wait_for(future, timeout)
        # hikari swallows listener exceptions into ExceptionEvent tasks
        # (fire-and-forget re-dispatches) — drain the queue they land in
        exceptions = await _drain_exceptions(queue)
    finally:
        bot.event_manager.unsubscribe(hikari.ExceptionEvent, _capture)

    delta = {
        key: entries[len(snapshot[key]) :]
        for key, entries in rest.interaction_log.items()
    }
    message_ids = [
        message.id
        for token, message in rest.webhook_messages.items()
        if token not in message_snapshot
    ]
    return PressResult(
        token=token,
        responses=[
            (rtype, payload) for _t, rtype, payload in delta["responses"]
        ],
        edits=[(mid, payload) for _t, mid, payload in delta["edits"]],
        deletes=[mid for _t, mid in delta["deletes"]],
        followups=[payload for _t, payload in delta["followups"]],
        modals=delta["modals"],
        exceptions=exceptions,
        message_ids=message_ids,
    )


def _token() -> str:
    return f"interaction-{next(_TOKENS)}"


def _base_payload(
    *,
    type_: int,
    token: str,
    user: dict[str, Any],
    channel_id: int,
    guild_id: int,
    member_permissions: int,
    data: dict[str, Any],
    message: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(next(_IDS)),
        "type": type_,
        "application_id": str(_APP_ID),
        "guild_id": str(guild_id),
        "channel": _channel_payload(channel_id),
        "member": _member_payload(user, guild_id, member_permissions),
        "token": token,
        "version": 1,
        "data": data,
        "locale": "en-US",
        "app_permissions": "0",
        "entitlements": [],
        "authorizing_integration_owners": {"0": str(_APP_ID)},
        "context": 0,
    }
    if message is not None:
        payload["message"] = message
    return payload


def _user_payload(uid: int, username: str) -> dict[str, Any]:
    return {
        "id": str(uid),
        "username": username,
        "discriminator": "0",
        "avatar": None,
        "global_name": username,
        "public_flags": 0,
    }


def _member_payload(
    user: dict[str, Any], guild_id: int, permissions: int
) -> dict[str, Any]:
    return {
        "user": user,
        "roles": [str(guild_id)],
        "joined_at": "2024-01-01T00:00:00.000000+00:00",
        "permissions": str(permissions),
    }


def _channel_payload(channel_id: int) -> dict[str, Any]:
    return {"id": str(channel_id), "type": 0, "name": "general"}


def _message_payload(
    message_id: int, channel_id: int, author: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": str(message_id),
        "channel_id": str(channel_id),
        "author": author,
        "content": "",
        "timestamp": "2024-01-01T00:00:00.000000+00:00",
        "edited_timestamp": None,
        "tts": False,
        "attachments": [],
        "embeds": [],
        "pinned": False,
        "type": 0,
        "flags": 0,
        "components": [],
    }


def _option_payload(
    name: str, value: Any, resolved: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Discord option payload; non-primitive types need resolved data."""
    if isinstance(value, bool):
        return {"name": name, "type": 5, "value": value}
    if isinstance(value, float):
        return {"name": name, "type": 10, "value": value}
    if isinstance(value, int):
        value_str = str(value)
        if value_str in resolved.get("channels", {}):
            return {"name": name, "type": 7, "value": value_str}
        if value_str in resolved.get(
            "members", {}
        ) or value_str in resolved.get("users", {}):
            return {"name": name, "type": 6, "value": value_str}
        if value_str in resolved.get("roles", {}):
            return {"name": name, "type": 8, "value": value_str}
        return {"name": name, "type": 4, "value": value}
    return {"name": name, "type": 3, "value": str(value)}
