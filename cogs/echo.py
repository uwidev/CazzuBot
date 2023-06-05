# Neccessary imports
import discord
from discord.ext import commands

from utility import _log  # What we use to log to console

# Define the cog here. Change Echo to whatever you want.
class Echo(commands.Cog):

    def __init__(self, bot):
        # This class needs a reference to the bot,
        # as it gets no references anywhere else.
        self.bot = bot
    
    # Listen for a specific event. Must be a couroutine.
    # For all events, see: https://discordpy.readthedocs.io/en/stable/api.html?highlight=on_message#event-reference
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.Member):
        # Listener parameters will vary based on the event.
        if user.id == self.bot.owner_id:
            # A lot of methods are coroutines, and must be await'ed.
            await reaction.message.channel.send("Hello there...")
    
    # Commands always needs this decorator. Must be a coroutine.
    @commands.command()
    async def echo(self, ctx, *, content: str):
        # Commands always need the parameters:
        # self: because method function
        # ctx:  the context in which this command was executed
        #       see https://discordpy.readthedocs.io/en/stable/ext/commands/api.html?highlight=bot%20owner#context
        # 
        # Anything past that are arguments to pass into the command as individual parameters, 
        # and will always be strngs UNLESS you convert it.
        # See about converters: https://discordpy.readthedocs.io/en/stable/ext/commands/commands.html#converters
        #
        # `*, content: str`
        # The last two arguments are special. `*` grabs the rest of the arguments and puts it into the variable content.

        # To send a message back to the channel the command was used in, just send it back to the context.
        await ctx.send(content)

# All cogs MUST have this on the bottom. Make sure you swap Echo to whatever your cog name is.
async def setup(bot: commands.Bot):
    await bot.add_cog(Echo(bot))