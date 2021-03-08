import discord
from discord.ext import commands
import db_user_interface
from utility import make_simple_embed

import customs.cog

def ranks_sort(arg):
        try:
            return int(arg)
        except:
            pass

        if arg.lower() in ['exp', 'frogs', 'frog']:
            if arg in ['frogs', 'frog']:
                return 'frogs_lifetime'
            return arg
        
        raise commands.ConversionError


class Rank(customs.cog.Cog):
    @commands.command(aliases=['rank'])
    async def ranks(self, ctx, mode:ranks_sort = 'exp', page=1):
        '''
        Shows the ranks of all members sorted by their experience points.

        Simply providing a number will let you view a page sorted by experience. If you want sort by frogs, be sure to provde the **mode** with **`frogs`**, followed by a page number if you so desire.
        '''
        if type(mode) == int:
            page = mode
            mode = 'exp'

        sorted_users = db_user_interface.fetch_all(self.bot.db_user)

        total_pages = len(sorted_users)//10+1
        if page > total_pages:
            page = total_pages
        elif page <= 0:
            page = 1

        sorted_users.sort(key=lambda user: (user[mode], user['exp' if mode == 'frogs_lifetime' else 'frogs_lifetime']), reverse=True)
        
        title ='Rankings'

        sorted_users_ids = list(map(lambda user: user['id'], sorted_users))
        placement = sorted_users_ids.index(ctx.message.author.id)
        ranking = 'You are ranked **`{place}`** out of **`{total}`**!'.format(place=placement + 1, total=len(sorted_users))
        
        display = 'Page {page} of {total}'.format(page=page, total=total_pages)

        lower = (page-1)*10
        upper = min((page-1)*10+10, len(sorted_users))
        
        display += '```py\n{place:8}{mode:<8}{user:20}\n'.format(place='Place', mode='Exp' if mode == 'exp' else 'Frogs', user='User')

        for i in range(lower, upper):
            try:
                if sorted_users[i]['id'] == ctx.message.author.id:
                    display += '{place:.<8}{count:.<8}{user:20}\n'.format(place='@'+str(i+1), count=int(sorted_users[i][mode]), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                elif i%2:
                    display += '{place:<8}{count:<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i][mode]), user=self.bot.get_user(sorted_users[i]['id']).display_name)
                else:
                    display += '{place:.<8}{count:.<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i][mode]), user=self.bot.get_user(sorted_users[i]['id']).display_name)
            except AttributeError:
                if sorted_users[i]['id'] == ctx.message.author.id:
                    display += '{place:.<8}{count:.<8}{user:20}\n'.format(place='@'+str(i+1), count=int(sorted_users[i][mode]), user=(await self.bot.fetch_user(sorted_users[i]['id'])).display_name)
                elif i%2:
                    display += '{place:<8}{count:<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i][mode]), user=(await self.bot.fetch_user(sorted_users[i]['id'])).display_name)
                else:
                    display += '{place:.<8}{count:.<8}{user:20}\n'.format(place=str(i+1), count=int(sorted_users[i][mode]), user=(await self.bot.fetch_user(sorted_users[i]['id'])).display_name)
            
        display += '```'

        comment = 'Currently being sorted by **{mode}**. To sort by {other}, try running `{pre}ranks {alt}`.'.format(mode='experience' if mode == 'exp' else 'lifetime frog captures', other='lifetime frog captures' if mode == 'exp' else 'experience', pre=self.bot.command_prefix, alt='frog' if mode == 'exp' else 'exp')

        desc = ranking + '\n\n' + display + '\n' + comment

        embed = make_simple_embed(title, desc)
        embed.set_footer(text='-sarono', icon_url='https://i.imgur.com/BAj8IWu.png')

        for user in sorted_users:
            member_id = user['id']
            member = self.bot.get_user(member_id)
            if member is not None:
                break
        
        embed.set_thumbnail(url=member.avatar_url)

        await ctx.send(embed=embed)


    @ranks.error
    async def ranks_error_handler(self, ctx, error):
        if isinstance(error, commands.BadArgument):
            print(error)
        else:
            raise error

    @commands.command()
    async def test(self, ctx):
        me = self.bot.get_user(310260458047275009)
        await ctx.send(me)


def setup(bot):
    bot.add_cog(Rank(bot))