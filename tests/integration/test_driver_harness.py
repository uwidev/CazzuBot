"""The FakeRest interaction-webhook lifecycle rules, pinned.

These are the Discord semantics the driver relies on to turn the manual
"didn't respond in time" / 404 bug classes into test failures:
one initial response per interaction, acked-token webhook access,
per-token message ownership, and ``@original`` only after a response type
that materialises a message.
"""

from __future__ import annotations

import pytest
import hikari

from tests.fakes import FakeRest


async def test_webhook_lifecycle_rules(fake_rest: FakeRest) -> None:
    rest = fake_rest

    # un-acked token: nothing can be edited
    with pytest.raises(hikari.NotFoundError):
        await rest.edit_webhook_message(1, "never-acked", 1001)

    # first response works; a second initial response 404s (like Discord)
    await rest.create_interaction_response(
        1, "tok", hikari.ResponseType.MESSAGE_CREATE, "hi"
    )
    with pytest.raises(hikari.NotFoundError):
        await rest.create_interaction_response(
            1, "tok", hikari.ResponseType.MESSAGE_CREATE, "again"
        )

    # edits must address an existing message owned by the token
    with pytest.raises(hikari.NotFoundError):
        await rest.edit_webhook_message(1, "tok", 999999)
    minted = rest.webhook_messages["tok"].id
    await rest.edit_webhook_message(1, "tok", minted, component=None)

    # cross-token edits are rejected even when the message exists
    await rest.create_interaction_response(
        1, "other", hikari.ResponseType.MESSAGE_CREATE, "theirs"
    )
    with pytest.raises(hikari.NotFoundError):
        await rest.edit_webhook_message(1, "other", minted)


async def test_original_only_after_message_response(
    fake_rest: FakeRest,
) -> None:
    rest = fake_rest

    # a bare defer (DEFERRED_MESSAGE_CREATE) materialises no message yet:
    # @original edits/delete/fetch all 404 like Discord
    await rest.create_interaction_response(
        1, "deferred", hikari.ResponseType.DEFERRED_MESSAGE_CREATE
    )
    with pytest.raises(hikari.NotFoundError):
        await rest.edit_interaction_response(1, "deferred", "x")
    with pytest.raises(hikari.NotFoundError):
        await rest.delete_interaction_response(1, "deferred")
    with pytest.raises(hikari.NotFoundError):
        await rest.fetch_interaction_response(1, "deferred")

    # DEFERRED_MESSAGE_UPDATE addresses the source message instead
    await rest.create_interaction_response(
        1, "updating", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    await rest.edit_interaction_response(1, "updating", component=None)
    await rest.delete_interaction_response(1, "updating")
