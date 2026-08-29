How do I… add persistent buttons & modals
=========================================

Interactive views are lightbulb **menus** — builders registered with a fixed
custom id. Because the id is fixed, the button survives restarts without
re-registration.


1. Attach a button
------------------

Build the row and carry it on the message from a command:

~~~~ python
import hikari

row = hikari.impl.MessageActionRowBuilder().add_interactive_button(
    hikari.ButtonStyle.PRIMARY,
    "badges:grant",
    label="Grant",
    emoji=utils.button_emoji(EMOJI_CUSTOM_ID),
)
await ctx.respond(embed=embed, component=row)
~~~~

The `counter` plugin's baka button is the reference
(`plugins/counter/extension.py`).


2. Handle presses
-----------------

Match the fixed custom id in a component-interaction listener:

~~~~ python
from cazzubot.listeners import guild_listener


@guild_listener(loader, hikari.InteractionCreateEvent)
async def on_interaction(event: hikari.InteractionCreateEvent) -> None:
    interaction = event.interaction
    if not isinstance(interaction, hikari.ComponentInteraction):
        return
    if interaction.custom_id != "badges:grant":
        return
    await _handle_grant(event.app, interaction)
~~~~


3. Confirm menus
----------------

For a Yes/No step, use the built-in `ConfirmMenu`
(`cazzubot.utils.ConfirmMenu`, a `lightbulb.components.Menu`):

~~~~ python
if not await ConfirmMenu(ctx, "Consume 1 badge?").confirm():
    return
~~~~


4. Modals
---------

Modals are lightbulb `modals.Modal` subclasses, shown via
`create_modal_response`. The poll plugin is the full reference
(`plugins/poll/extension.py`):

~~~~ python
from lightbulb.components import modals


class BadgeModal(modals.Modal):
    def __init__(self) -> None:
        super().__init__()
        self.badge_input = self.add_text_input("Badge key", min_length=1)


custom_id = "badges:submit"
modal = BadgeModal()
await interaction.create_modal_response(
    "Add badge", custom_id, components=modal
)
~~~~

Attach the handler for the modal's session, then act on submit:

~~~~ python
await modal.attach(bot.lightbulb, custom_id, timeout=300)


@override
async def on_submit(self, ctx: modals.ModalContext) -> None:
    key = ctx.value_for(self.badge_input)
    ...
~~~~


5. Testing
----------

Drive buttons and modals offline with the driver — see **write a plugin
test**:

~~~~ python
press = await press_button(
    bot, custom_id="badges:grant", message_id=mid, user_id=1
)
~~~~

`attached_buttons(bot)` lists the button custom ids on attached menus, and
`modal_input_custom_id(modal)` gives the input's id for the values dict.
