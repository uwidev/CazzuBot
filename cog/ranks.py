'''
If you ever plan to implement promote/demote commands, only changing experience would be perfectly fine. The next time the user talks they will be updated.
However, if you wanted instant updates, you will have to manually adjust the exp, database, and then member roles. The former is quicker and will work.
'''

from math import sin
import asyncio

import discord
from discord.ext import commands
from copy import copy

import db_user_interface, db_guild_interface
from utility import make_error_embed, is_admin, make_simple_embed_t, quick_embed, request_user_confirmation, EmbedSummary
import customs.cog

_OLD_RANKS = {
    547245884426158100:	465,
    547245885629923328:	2326,
    547245887483674625:	6513,
    547245889404796928:	13957,
    547245890969272320:	25588,
    547245892328226846:	42536,
    547245893565546506:	65132,
    547245894953730054:	94907,
    547245896266678272:	132591,
    547245897541484573:	179114,
    547245898816552961:	235407,
    547245899575984143:	302400,
    0 : 0
}

_OLD_RANKS_LIST = list(_OLD_RANKS.keys())

# ==============================================================
# Summary Embed Override
# ==============================================================
_RANK_EMBED_TITLE = 'Rank Promotion! 🎉'
_RANK_EMBED_DESCRIPTION = '**__Rank:__ {old} -> {new}**'
_RANK_EMBED_THUMBNAIL = 'https://i.imgur.com/iBtT4e1.png'
_RANK_EMBED_COLOR = 0x00B1F5

from tatsu.wrapper import ApiWrapper

class Ranks(customs.cog.Cog):
    def __init__(self, bot):        
        super().__init__(bot)
        self.bot.tatsu = ApiWrapper(key='LiT9zi3WWG-JEqVvWAMYSrsgbaREWuJON') # DANGER PUBLIC API KEY


    @commands.command()
    async def tatsu(self, ctx):
        if ctx.author.id != 338486462519443461:
            return
        
        # res = await self.bot.tatsu.get_guild_rankings(ctx.guild.id)
        # for member in res.rankings:
        #     print(member.score)

        settings_guild = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        settings_rank_thresholds = settings_guild['ranks']['level_thresholds']

        threshold_inv = {v:k for k,v in settings_rank_thresholds.items()}

        p = await self.bot.tatsu.get_member_ranking(293796316193095690, ctx.author.id)
        
        score = p.score
        rank = min(_OLD_RANKS.items(), key=lambda kv: (1 if int(kv[1]) <= score else float('inf')) * abs(int(kv[1])-score))[0]
        print(score)
        print(rank)        

        to_rank = _OLD_RANKS[rank]
        next_rank = _OLD_RANKS_LIST[_OLD_RANKS_LIST.index(rank) + 1]

        if next_rank == 0:
            pass # this means the user is above strongest baka, different formula
            return

        to_next_rank =  _OLD_RANKS[next_rank]
        
        caz_rank_lvl = threshold_inv[rank]
        caz_next_rank_lvl = threshold_inv[next_rank]

        cog_level = self.bot.get_cog('Levels')
        
        caz_rank_exp = await cog_level.level_exp(ctx, int(caz_rank_lvl))
        caz_next_rank_exp = await cog_level.level_exp(ctx, int(caz_next_rank_lvl))

        progress = (score-to_rank)/(to_next_rank-to_rank)

        cog_level = self.bot.get_cog('Levels')
        
        percent = (score - to_rank)/(to_next_rank - to_rank)

        exp = caz_rank_exp + (percent * (caz_next_rank_exp - caz_rank_exp))


    async def on_experience(self, message: discord.Message, level: int):
        # Handles ranks when a member receives experience.
        #
        # Returns summary:dict() if there was a positive change
        # Returns None if there was no or a negative change
        embed = EmbedSummary()
        
        settings_guild = db_guild_interface.fetch(self.bot.db_guild, message.guild.id)
        settings_rank = settings_guild['ranks']
        if settings_rank['op']:
            settings_rank_thresholds = settings_rank['level_thresholds']
            
            member = message.author
            db_member = db_user_interface.fetch(self.bot.db_user, member.id)

            rank_old_id = db_member['rank']
            rank_new_id = await self.from_level(message.guild.id, level)

            # Handle rank changes
            if rank_old_id != rank_new_id:
                db_member['rank'] = rank_new_id
                db_user_interface.write(self.bot.db_user, member.id, db_member)

            # Summary
            rank_old = message.guild.get_role(rank_old_id) if rank_old_id is not None else None
            rank_new = message.guild.get_role(rank_new_id) if rank_new_id is not None else None

            ranks_ids = list(settings_rank_thresholds.values())
            ranks_ids.insert(0, None)

            if rank_old == rank_new or ranks_ids.index(rank_old_id) > ranks_ids.index(rank_new_id): # Force consistency between member and database
                # Ensure user has no other ranks except their database rank
                await self.member_clean(member, rank_new)
                # If they don't have their internal database rank, give it to them
                if rank_new is not None and rank_new not in member.roles:
                    await member.add_roles(rank_new, reason="Preserving Discord model with internal database")
                
                # print('\n//////////////////////////////////////////////////////////////')
                # print(f"/// {member} has changed rank from {'None' if rank_old is None else rank_old} to {rank_new}!")
                # print('//////////////////////////////////////////////////////////////\n')
            
            else: # Inversely checks for positive changes to ranks, if so return summary
                await self.member_clean(member, rank_new)
                await member.add_roles(rank_new, reason="Preserving Discord model with internal database")
                print('\n//////////////////////////////////////////////////////////////')
                print(f"/// {member} has changed rank from {'None' if rank_old is None else rank_old} to {rank_new}!")
                print('//////////////////////////////////////////////////////////////\n')
                
                update_rank = _RANK_EMBED_DESCRIPTION.format(old='`None`' if rank_old is None else rank_old.mention, new=rank_new.mention)
                embed = EmbedSummary(_RANK_EMBED_TITLE, update_rank, _RANK_EMBED_THUMBNAIL, _RANK_EMBED_COLOR)

            # Further calls that depend on ranks
            # NONE
            
            
        return embed


    async def db_to_roles(self, guild):
        settings_guild = db_guild_interface.fetch(self.bot.db_guild, guild.id)
        settings_rank_thresholds = settings_guild['ranks']['level_thresholds']

        ranks = list()
        for role_id in settings_rank_thresholds.values():
            ranks.append(guild.get_role(role_id))

        return ranks


    async def from_level(self, gid, level:int):
        settings_guild = db_guild_interface.fetch(self.bot.db_guild, gid)
        settings_rank_thresholds = settings_guild['ranks']['level_thresholds']

        ranks = copy(settings_rank_thresholds) # copy so we don't change the og rank list
        ranks[0] = None # used to as a floor for from_levels to so a user doesn't get a rank when below all ranks
        return min(ranks.items(), key=lambda kv: (1 if int(kv[0]) <= level else float('inf')) * abs(int(kv[0])-level))[1]


    async def is_rank_change(self, guild, level1, level2):
        # Compares the ranks given two levels. 
        # 
        # Returns a tuple where:
        # element 0 denotes that they are not the same
        # element 1 denotes that rank 1 is ranked lower than rank 2
        # element 2 is rank1 from level1
        # element 3 is rank2 from level2
        id = guild.id

        settings_guild = db_guild_interface.fetch(self.bot.db_guild, gid)
        settings_rank_thresholds = settings_guild['ranks']['level_thresholds']

        rank1 = await self.from_levels(gid, level1)
        rank2 = await self.from_levels(gid, level2)

        if rank1 is None and rank2 is not None:
            rank2 = guild.get_role(rank2)
            return (True, True, None, rank2)
        elif rank1 is not None and rank2 is None:
            rank1 = guild.get_role(rank1)
            return (True, False, rank1, None)

        rank1 = guild.get_role(rank1)
        rank2 = guild.get_role(rank2)
        ranks_inv = {v:k for k,v in settings_rank_thresholds.items()}
        return (rank1.id != rank2.id, ranks_inv[rank1.id] < ranks_inv[rank2.id], rank1, rank2)


    async def apply_rank(self, member:discord.Member, rank:discord.Role):
        db_member = db_user_interface.fetch(self.bot.db_user, member.id)
        await self.user_clean(member)

        db_member['rank'] = rank.id
        await member.add_roles(rank)


    async def get_user_highest(self, member):
        settings_guild = db_guild_interface.fetch(self.bot.db_guild, message.guild.id)
        settings_rank_thresholds = settings_guild['ranks']['level_thresholds']

        ranks = list()
        for role_id in settings_rank_thresholds.values():
            ranks.append(message.guild.get_role(role_id))
        
        for rank in reversed(ranks):
            if rank in member.roles:
                return rank
        
        return None


    async def member_clean(self, member: discord.Member, current_rank = None):
        ranks = await self.db_to_roles(member.guild)
        if current_rank is not None:
            ranks.remove(current_rank)
        to_remove = list()

        for rank in ranks:
            if rank in member.roles:
                to_remove.append(rank)
        
        await member.remove_roles(*to_remove, reason="Preserving Discord model with internal database")


    async def summary_payload(self, gid, rank_old, rank_new):
        assert(rank_old != rank_new)

        payload = dict()
        payload['Rank'] = ('`None`' if rank_old is None else rank_old.mention, rank_new.mention)

        return payload


    async def send_rank_up(self, channel, member, summary_dict:dict):
        embed = make_simple_embed_t(_RANK_EMBED_TITLE, _RANK_EMBED_DESCRIPTION.format(user=member.name))
        summary = '\n'.join(_RANK_EMBED_SUMMARY_TEMPLATE.format(name=key, old=val[0], new=val[1]) for key,val in summary_dict.items())
        embed.add_field(name='**Summary**', value=summary, inline=False)
        embed.set_thumbnail(url=_RANK_EMBED_THUMBNAIL)

        # print(f'title: {embed.title}\ndesc: {embed.description}\nsummary: {summary}')
        await channel.send(member.mention, embed=embed)


    @commands.group(aliases=['rank'], invoke_without_command=True)
    async def ranks(self, ctx):
        pass

    
    @ranks.command(name='on', aliases=['enable', 'enabled'])
    @is_admin()
    async def ranks_on(self, ctx):
        '''
        Turning on server ranks will immediately start to apply and remove role ranks to members who talk.
        '''
        if await request_user_confirmation(ctx, self.bot, 'Are you sure you want to make server rankings active?', delete_after=True):
            settings = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
            settings['ranks']['op'] = True

            db_guild_interface.write(self.bot.db_guild, ctx.guild.id, settings)

            await quick_embed(ctx, 'success', 'Ranks will now be actively applied and removed.')


    @ranks.command(name='off', aliases=['disable', 'disabled'])
    @is_admin()
    async def ranks_off(self, ctx):
        '''
        Turn off server ranks.
        '''
        settings = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
        settings['ranks']['op'] = False

        db_guild_interface.write(self.bot.db_guild, ctx.guild.id, settings)

        await quick_embed(ctx, 'success', 'Ranks will no longer be actively applied and removed.')


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
        
        # Sort by level for easier reading/formatting later
        settings_rank_thresholds = {k:v for k,v in sorted(settings_rank_thresholds.items(), key=lambda kv: int(kv[0]))}
        
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

    @ranks.command(name='migrate')
    @is_admin()
    async def ranks_migrate(self, ctx, member: discord.Member):
        '''
        Given an old user, look into Tatsu API and convert their tatsu rank to Cazzu Rank. Add this to whatever exp they currently have.
        '''
        if await request_user_confirmation(ctx, self.bot, f'Are you sure you want to migrate {member.mention}\'s tatsu score?\n\nThis should only every be called once on a user.', delete_after=True):
            settings = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
            ranks_threshold = settings['ranks']['level_thresholds']

            threshold_inv = {v:k for k, v in ranks_threshold.items()}

            ranks = await self.db_to_roles(ctx.guild)
            
            cog_level = self.bot.get_cog('Levels')
            level_exp_map = self.bot.get_cog('Levels').LEVEL_THRESHOLDS
            
            tatsu_member = await self.bot.tatsu.get_member_ranking(ctx.guild.id, member.id)
            tatsu_score = tatsu_member.score
            
            tatsu_rank = min(_OLD_RANKS.items(), key=lambda kv: (1 if int(kv[1]) <= tatsu_score else float('inf')) * abs(int(kv[1])-tatsu_score))[0]
            
            tatsu_to_rank = _OLD_RANKS[tatsu_rank]
            tatsu_next_rank = _OLD_RANKS_LIST[_OLD_RANKS_LIST.index(tatsu_rank) + 1]

            if tatsu_next_rank == 0: # it means they strongest, use different formula
                # print('user is strongest...')
                caz_strongest_score = await cog_level.level_exp(ctx, 100)
                # print(caz_strongest_score)

                tatsu_score_diff = tatsu_score - _OLD_RANKS[tatsu_rank]
                percent_more = tatsu_score_diff / _OLD_RANKS[tatsu_rank]

                extra_exp = caz_strongest_score * percent_more * 0.50

                db_member = db_user_interface.fetch(self.bot.db_user, tatsu_member.user_id)
                old = db_member['exp']
                
                db_member['exp'] += caz_strongest_score + extra_exp
            
            else:
                tatsu_to_next_rank = _OLD_RANKS[tatsu_next_rank]

                caz_rank_level = threshold_inv[tatsu_rank]
                caz_next_rank_level = threshold_inv[tatsu_next_rank]

                caz_rank_exp = await cog_level.level_exp(ctx, int(caz_rank_level))
                caz_next_rank_exp = await cog_level.level_exp(ctx, int(caz_next_rank_level))

                tatsu_progress_percent = (tatsu_score-tatsu_to_rank)/(tatsu_to_next_rank-tatsu_to_rank)
                
                # db_member = db_user_interface.fetch(self.bot.db_user, ctx.author.id)
                # print(db_member['exp'] + (tatsu_progress_percent * (caz_next_rank_exp - caz_rank_exp)))

                db_member = db_user_interface.fetch(self.bot.db_user, tatsu_member.user_id)
                # print(db_member['exp'], tatsu_progress_percent * (caz_next_rank_exp - caz_rank_exp))
                old = db_member['exp']
                cazzu_to_next_progress_exp = (tatsu_progress_percent * (caz_next_rank_exp - caz_rank_exp))
                
                db_member['exp'] += caz_rank_exp + cazzu_to_next_progress_exp
                
            this_member = ctx.guild.get_member(tatsu_member.user_id)
            print(f"{this_member} adjusted exp from {old} to {db_member['exp']}")
            db_user_interface.write(self.bot.db_user, tatsu_member.user_id, db_member)
        
            await quick_embed(ctx, 'success', f'{member.mention}\'s tatsu score has been migrated to Cazzubot!')


    # This migrate command determins the percent a user is from one rank the next rank and uses that percent
    # to determine how much exp to give a user form what they currently are. It is partially a migration but no not really.
    #
    # @ranks.command(name='migrate')
    # @is_admin()
    # async def ranks_migrate(self, ctx):
    #     '''
    #     With ranks set, sync the database to the guild such that their experience matches the minimum for their highest rank.
    #     '''
    #     if await request_user_confirmation(ctx, self.bot, 'Are you sure you want to migrate server ranks to CazzuBot experience?', delete_after=True):
    #         settings = db_guild_interface.fetch(self.bot.db_guild, ctx.guild.id)
    #         ranks_threshold = settings['ranks']['level_thresholds']

    #         threshold_inv = {v:k for k, v in ranks_threshold.items()}

    #         ranks = await self.db_to_roles(ctx.guild)
            
    #         async with ctx.typing():
    #             cog_level = self.bot.get_cog('Levels')
    #             level_exp_map = self.bot.get_cog('Levels').LEVEL_THRESHOLDS
                
    #             for i in range(0, 5):
    #                 result = await self.bot.tatsu.get_guild_rankings(ctx.guild.id, offset=100*i)
    #                 # result = await self.bot.tatsu.get_member_ranking(ctx.guild.id, ctx.author.id)
    #                 for member in result.rankings:
    #                     # member = result
    #                     tatsu_score = member.score
                        
    #                     tatsu_rank = min(_OLD_RANKS.items(), key=lambda kv: (1 if int(kv[1]) <= tatsu_score else float('inf')) * abs(int(kv[1])-tatsu_score))[0]
                        
    #                     tatsu_to_rank = _OLD_RANKS[tatsu_rank]
    #                     tatsu_next_rank = _OLD_RANKS_LIST[_OLD_RANKS_LIST.index(tatsu_rank) + 1]

    #                     if tatsu_next_rank == 0: # it means they strongest, use different formula
    #                         # print('user is strongest...')
    #                         caz_strongest_score = await cog_level.level_exp(ctx, 100)
    #                         # print(caz_strongest_score)

    #                         tatsu_score_diff = tatsu_score - _OLD_RANKS[tatsu_rank]
    #                         percent_more = tatsu_score_diff / _OLD_RANKS[tatsu_rank]

    #                         extra_exp = caz_strongest_score * percent_more * 0.50

    #                         db_member = db_user_interface.fetch(self.bot.db_user, member.user_id)
    #                         old = db_member['exp']
    #                         db_member['exp'] += extra_exp
    #                     else:
    #                         tatsu_to_next_rank = _OLD_RANKS[tatsu_next_rank]

    #                         caz_rank_level = threshold_inv[tatsu_rank]
    #                         caz_next_rank_level = threshold_inv[tatsu_next_rank]

    #                         caz_rank_exp = await cog_level.level_exp(ctx, int(caz_rank_level))
    #                         caz_next_rank_exp = await cog_level.level_exp(ctx, int(caz_next_rank_level))

    #                         tatsu_progress_percent = (tatsu_score-tatsu_to_rank)/(tatsu_to_next_rank-tatsu_to_rank)
                            
    #                         # db_member = db_user_interface.fetch(self.bot.db_user, ctx.author.id)
    #                         # print(db_member['exp'] + (tatsu_progress_percent * (caz_next_rank_exp - caz_rank_exp)))

    #                         db_member = db_user_interface.fetch(self.bot.db_user, member.user_id)
    #                         # print(db_member['exp'], tatsu_progress_percent * (caz_next_rank_exp - caz_rank_exp))
    #                         old = db_member['exp']
    #                         db_member['exp'] += (tatsu_progress_percent * (caz_next_rank_exp - caz_rank_exp))
                            
    #                     this_member = ctx.guild.get_member(member.user_id)
    #                     # print(f"{this_member} adjusted exp from {old} to {db_member['exp']}")
    #                     db_user_interface.write(self.bot.db_user, member.user_id, db_member)
                    
    #                 await asyncio.sleep(3)
            
    #         await quick_embed(ctx, 'success', f'Ranks have been migrated to Cazzubot!')
        



def setup(bot):
    bot.add_cog(Ranks(bot))