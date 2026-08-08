"""Plain exceptions for user-input validation (framework-agnostic).

Service and core modules raise these instead of ``commands.BadArgument``
so they never import the framework. The command edge translates them back
into user-visible feedback (see ``CazzuBot.on_command_error``).
"""


class UserInputError(Exception):
    """The user's input was invalid; the message is safe to show them."""
