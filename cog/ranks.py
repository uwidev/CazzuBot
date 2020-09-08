import discord
from discord.ext import commands
import db_user_interface


def ranks_sort(arg):
        print(arg.lower())
        if arg.lower() in ['exp', 'frogs', 'frog']:
            if arg == 'frog':
                return 'frogs'
            return arg
        
        raise commands.ConversionError


class Rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['rank'])
    async def ranks(self, ctx, key:ranks_sort = 'exp', page=1):
        '''
        Shows the ranks of all members sorted by their experience points.
        '''
        sorted_users = db_user_interface.fetch_all(self.bot.db_user)

        total_pages = len(sorted_users)//10+1
        if page > total_pages:
            page = total_pages
        elif page <= 0:
            page = 1

        sorted_users.sort(key=lambda user: (user[key], user['exp' if key == 'frogs' else 'frogs']), reverse=True)
        
        ranking = 'Page {page} of {total}\n\n'.format(page=page, total=total_pages)
        embed = discord.Embed(
                        title='Rankings',
                        color=0x9edbf7
                    )
        embed.set_footer(text='-sarono', icon_url='https://i.imgur.com/BAj8IWu.png')
        embed.set_thumbnail(url=self.bot.get_user(sorted_users[0]['id']).avatar_url)

        lower = (page-1)*10
        upper = min((page-1)*10+10, len(sorted_users))

        for i in range(lower, upper):
            if self.bot.get_user(sorted_users[i]['id']) == None:
                print(sorted_users[i]['id'])
            ranking += '**`# {}` **'.format(i+1) + self.bot.get_user(sorted_users[i]['id']).mention + '\n'

        embed.description = ranking

        await ctx.send(embed=embed)


    @ranks.error
    async def ranks_error_handler(self, ctx, error):
        if isinstance(error, commands.BadArgument):
            print(error)
        else:
            raise error


def setup(bot):
    bot.add_cog(Rank(bot))