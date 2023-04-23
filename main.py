import os
import traceback

import discord
from discord.ext import commands
import tinydb

from secret import TOKEN, OWNER_ID


# Intents need to be set up to let discord know what we want for requests
intents = discord.Intents.default()
intents.message_content = True

# Run bot
bot = commands.Bot('d!', intents=intents, owner_id=OWNER_ID)


@bot.event
async def on_ready():
    print(f'Loading extensions...')

    await load_cogs()

    print(f'Logged in as {bot.user.name}')


async def load_cogs():
    for file in os.listdir('cogs'):
        if file.endswith('.py'):
            try:
                await bot.load_extension(f'cogs.{file[0:-3]}')
            except Exception as e:
                print(traceback.print_exception(e))


# turn cog reload into group command with check for admin perms
# @bot.group()
# async def cog(ctx: commands.Context):
#     if ctx.channel.permissions_for(ctx.author).administrator:
#         load_cogs()


#     @commands.command()
#     async def reload(self, ctx, *, ext_name):
#         ext = 'cog.' + ext_name
#         if ext not in self.bot.extensions:
#             await ctx.send(embed=make_simple_embed_t('ERROR', 'Extension doesn\'t exist or you can\'t spell!'))
#             raise commands.BadArgument
        
#         try:
#             self.bot.reload_extension(ext)
#             await ctx.send(embed=make_simple_embed_t('Success', f'{ext_name.capitalize()} has been reloaded'))
#         except Exception as e:
#             await ctx.send(embed=make_simple_embed_t('ERROR', 'There appears to be a problem with your code, baka.'))
#             raise e


#     @commands.command()
#     async def load(self, ctx, ext_name):
#         ext = ext_name + '.py'
#         dir = os.listdir('cog')
        
#         if ext in dir:
#             try:
#                 self.bot.load_extension('cog.' + ext_name)
#                 await ctx.send(embed=make_simple_embed_t('Success', f'{ext_name.capitalize()} has been loaded'))
#             except Exception as e:
#                 await ctx.send(embed=make_simple_embed_t('ERROR', 'Something terrible happened!'))
#                 raise e
#         else:
#             await ctx.send(embed=make_simple_embed_t('ERROR', 'File doesn\'t exist or you can\'t spell!'))


#     @commands.command()
#     async def unload(self, ctx, ext_name):
#         ext = 'cog.' + ext_name
#         if ext not in self.bot.extensions:
#             await ctx.send(embed=make_simple_embed_t('ERROR', 'Extension wasn\'t loaded to begin with!'))
#             raise commands.BadArgument
        
#         dir = os.listdir('cog')
#         if ext_name + '.py' in dir:
#             try:
#                 self.bot.unload_extension('cog.' + ext_name)
#                 await ctx.send(embed=make_simple_embed_t('Success', f'{ext_name.capitalize()} has been unloaded'))
#             except Exception as e:
#                 await ctx.send(embed=make_simple_embed_t('ERROR', 'Something terrible happened!'))
#                 raise e
#         else:
#             await ctx.send(embed=make_simple_embed_t('ERROR', 'Extension doesn\'t exist or you can\'t spell!'))




if __name__ == "__main__":
    bot.run(TOKEN)