from typing import Annotated

from discord.ext import commands


class PositiveIntConverter(commands.Converter):
    """Ensures passed argument is a positive, non-zero number."""

    async def convert(self, ctx, arg) -> int:
        try:
            ret = int(arg)
        except ValueError as err:
            msg = f"Could not convert {arg} to integer."
            raise commands.BadArgument(msg) from err

        if ret < 1:
            msg = f"Argument {arg} must be a positive integer."
            raise commands.BadArgument(msg)

        return ret


PositiveInt = Annotated[int, PositiveIntConverter]
