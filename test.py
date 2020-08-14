# import os, asyncio, copy
# from collections import OrderedDict

# import discord
# from discord.ext import commands, tasks
# from tinydb import TinyDB
# from interfacedb import get_guild_conf
# from secret import TOKEN


# bot = commands.Bot(command_prefix='c!')

# c = 0

# @tasks.loop(count=1)
# async def printer(ctx):
#     await asyncio.sleep(1)
#     global c
#     await ctx.send(c)
#     c += 1
#     await asyncio.sleep(0)
    

# @bot.command()
# async def test(ctx):
#     print('running the test...')
#     copy.copy(printer).start(ctx)
#     await asyncio.sleep(1)
#     copy.copy(printer).start(ctx)
#     copy.copy(printer).start(ctx)
#     copy.copy(printer).start(ctx)
#     await asyncio.sleep(1)
#     copy.copy(printer).start(ctx)


# @bot.event
# async def on_ready():
#     print(f'Logged in as: {bot.user.name}')
#     print(f'With ID: {bot.user.id}')

# if __name__ == '__main__':
#     bot.run(TOKEN)

class C():
    def test():
        print('blah')

one = C()
two = C()

print(one.test)
print(two.test)