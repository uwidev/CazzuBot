from math import sin

import discord
from discord.ext import commands
from copy import copy

import db_user_interface, db_guild_interface
from utility import make_error_embed, is_admin, make_simple_embed_t, quick_embed, request_user_confirmation
import customs.cog


class Ranks(customs.cog.Cog):
    def __init__(self, bot):
        super().__init__(bot)

    async def from_levels(self, gid, rank_lvl_ids, level:int):
        ranks = copy(rank_lvl_ids) # copy so we don't change the og rank list
        ranks[0] = None # used to as a floor for from_levels to so a user doesn't get a rank when below all ranks
        return min(ranks.items(), key=lambda kv: (1 if level >= int(kv[0]) else float('inf')) * abs(int(kv[0])-level))[1]


    async def on_experience(self, message, exp):
        # print('\n>>> ranks.on_experience')
        settings_guild = db_guild_interface.fetch(self.bot.db_guild, message.guild.id)
        settings_rank_thresholds = settings_guild['ranks']['level_thresholds']

        user = message.author

        level = await self.bot.get_cog('Levels').from_experience(exp)
        # print(f'=== level : {level}')
        rank_id = await self.from_levels(message.guild.id, settings_rank_thresholds, level)
        # print(f'=== rank_id : {rank_id}')
        rank = message.guild.get_role(rank_id)
        # print(f'=== calculated current rank: {rank}')

        ranks = list()
        for role_id in settings_rank_thresholds.values():
            ranks.append(message.guild.get_role(role_id))        

        if rank is None:
            for r in (ranks):
                try:
                    await user.remove_roles(r, reason='Rank change')
                except (discord.Forbidden, discord.HTTPException):
                    pass
        elif rank not in message.author.roles:
            for r in ranks:
                try:
                    await user.remove_roles(r, reason='Rank change')
                except (discord.Forbidden, discord.HTTPException):
                    pass

            try:
                await user.add_roles(rank, reason='Rank change')
            except (discord.Forbidden, discord.HTTPException):
                pass

            print('\n//////////////////////////////////////////////////////////////')
            print(f"/// {user} has changed ranks to {rank}!")
            print('//////////////////////////////////////////////////////////////\n')


    @commands.group(aliases=['rank'])
    async def ranks(self, ctx):
        pass

    @ranks.command(name='add')
    @is_admin()
    async def ranks_add(self, ctx, rank_level_threshold:int, *, rank:discord.Role):
        # print(f'>>> ranks_add args {ctx.args}')
        # print(f'>>> ranks_add kwargs {ctx.kwargs}')
        if rank_level_threshold < 1 or rank_level_threshold > 999:
            embed = make_error_embed(f'Level must be between 1 and 999.\n\nYou provided me with level **`{rank_level_threshold}`**.')
            await ctx.send(embed=embed)
            return
        
        settings_guild = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        settings_rank_thresholds = settings_guild['ranks']['level_thresholds']

        if rank.id in settings_rank_thresholds.values():
            to_rank = {v:k for k,v in settings_rank_thresholds.items()}[rank.id]
            embed = make_error_embed(f'{rank.mention} is already registered as a rank!\n\nUsers will reach this rank at level **`{to_rank}`**.')
            await ctx.send(embed=embed)
            return

        level = str(rank_level_threshold)
        if level in settings_rank_thresholds:
            rank_id = settings_rank_thresholds[level]
            rank = ctx.guild.get_role(rank_id)
            embed = make_error_embed(f'Level {level} is already registered for rank {rank.mention}.')
            await ctx.send(embed=embed)
            return

        settings_rank_thresholds[level] = rank.id
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, settings_guild)

        await quick_embed(ctx, 'success', f'Reaching level **`{rank_level_threshold}`** will now promote users to {rank.mention}.')


    @ranks.command(name='addmany')
    async def ranks_addmany(self, ctx, *, args):
        # print(f'>>> ranks_addmany args {ctx.args}')
        # print(f'>>> ranks_addmany kwargs {ctx.kwargs}')

        sep_pairs = args.split('|')

        if len(sep_pairs) % 2 == 1:
            await quick_embed(ctx, 'error', 'You are missing a level or rank for a pair.')
        
        args_pair = list(pair.strip().split(' ', 1) for pair in sep_pairs)

        for i in range(len(args_pair)):
            args_pair[i][1] = await commands.RoleConverter().convert(ctx, args_pair[i][1])

        for level, rank in args_pair:
            ctx.command = await self.bot.get_command('ranks add')(ctx, int(level), rank=rank)

            # print(f'>>> expected ranks_add args {ctx.args}')
            # print(f'>>> expected ranks_add kwargs {ctx.kwargs}')
            # await self.bot.invoke(ctx)
            pass # here we need to call ranks_add as if a user was calling it


    @ranks.command(name='remove', aliases=['del', 'delete'])
    @is_admin()
    async def ranks_remove(self, ctx, *, rank:discord.Role):
        settings_guild = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        settings_rank_thresholds = settings_guild['ranks']['level_thresholds']

        if rank.id not in settings_rank_thresholds.values():
            embed = make_error_embed(f'{rank.mention} is not registered as a rank.')
            await ctx.send(embed=embed)
            return

        to_rank = {v:k for k,v in settings_rank_thresholds.items()}[rank.id]
        settings_rank_thresholds.pop(to_rank)
        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, settings_guild)

        await quick_embed(ctx, 'success', f'Removed rank {rank} from ranks.\n\nThis rank was originally attained at level **`{to_rank}`**.')


    @ranks.command(name='clear', aliases=['clean'])
    @is_admin()
    async def ranks_clear(self, ctx):
        # TODO show all ranks to confirm before clearing
        if await request_user_confirmation(ctx, self.bot, 'Are you sure you would like to clear ranks?', delete_after=True):
            settings_guild = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
            settings_rank_thresholds = settings_guild['ranks']['level_thresholds']
            settings_rank_thresholds.clear()
            db_guild_interface.write(self.bot.db_guild, ctx.guild.id, settings_guild)

            await quick_embed(ctx, 'success', f'Ranks and their level requirements have been cleared!')


def setup(bot):
    bot.add_cog(Ranks(bot))