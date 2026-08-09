"""ConfirmMenu regression tests — menu clicks must ack the interaction.

lightbulb 3.x delivers menu callbacks an un-acknowledged interaction; a
callback that edits/deletes via the webhook without acking first dies with
``10015 Unknown Webhook`` and the click shows "did not respond in time".
"""

from __future__ import annotations


from cazzubot import utils
from tests.fakes import (
    FakeInteraction,
    FakeMenuContext,
    FakeMember,
    menu_button,
)


async def test_confirm_yes_acks_then_deletes_prompt(
    author: FakeMember,
) -> None:
    menu = utils.ConfirmMenu(author_id=author.id)
    mctx = FakeMenuContext(FakeInteraction(id=1, member=author))

    await menu_button(menu).callback(mctx)

    assert menu.value is True
    # the click was acknowledged (invisible update), then the prompt
    # (the initial response) was deleted
    assert mctx.deferred is True
    assert mctx.deleted == [utils.INITIAL_RESPONSE_IDENTIFIER]
    assert mctx.stopped is True


async def test_confirm_keeps_prompt_acks_by_editing(
    author: FakeMember,
) -> None:
    menu = utils.ConfirmMenu(author_id=author.id, delete_after=False)
    mctx = FakeMenuContext(FakeInteraction(id=1, member=author))

    await menu_button(menu).callback(mctx)

    assert menu.value is True
    # acked (invisible update), then the prompt's buttons are stripped
    assert mctx.deferred is True
    assert mctx.edits == [
        {
            "response_id": utils.INITIAL_RESPONSE_IDENTIFIER,
            "component": None,
        }
    ]
    assert mctx.stopped is True


async def test_confirm_ignores_foreign_clicks(
    author: FakeMember,
) -> None:
    menu = utils.ConfirmMenu(author_id=author.id)
    foreign = FakeMember(id=999, name="other")
    mctx = FakeMenuContext(FakeInteraction(id=1, member=foreign))

    await menu_button(menu).callback(mctx)

    assert menu.value is None
    assert mctx.sent[0].content == "This prompt is not for you."
    assert mctx.sent[0].ephemeral is True
    assert mctx.stopped is False
