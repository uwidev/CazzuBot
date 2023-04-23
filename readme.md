## How to develop
All functionality of the bot should be developed within `/cogs`.

Each file within `/cogs` define its own ecosystem. For example, all functionality relating to **frogs** should be in some file `frogs.py`. If said file is too long/big, it may be better to split the cog into various files, named as such `frogs_comamnds.py`, `frogs_listener.py`.

What are cogs? Cogs can be thought as a collection of commands, states, event listeners, etc. in one class. Cogs are loaded onto the bot at runtime and extend the functionality of the bot. It's modular and can be hot-swapped.
https://discordpy.readthedocs.io/en/stable/ext/commands/cogs.html

How to write a cog and commands? See `/cogs/echo.py`.

To try to get familiar with writing commands, try writing a simple math command as a cog.