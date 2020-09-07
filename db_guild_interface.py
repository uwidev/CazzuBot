# Manages the TinyDB database and ensures that data is written/read safely.

from tinydb import Query
from utility import ReadOnlyDict


# Consider making this a class instead of a dictionary?
guild_settings_default = ReadOnlyDict({
    'id':None,
    'groups':{
        'verify':{
            'op':False,
            'channel':None,
            'message':None,
            'emoji':None,
            'role':None
        },
        'welcome':{
            'op':False,
            'channel':None,
            'content':'{user}',
            'title':'Welcome to the server',
            'description':'Make sure you take a good look at the rules!'
        },
        'counter':{
            'op':False,
            'channel':None,
            'message':None,
            'count':0,
            'emoji':'⚪',
            'title':'Number of times people have touched the baka button',
            'description':'**> {count}**',
            'footer':'Looks like there\'s no bakas as of recent...',
            'thumbnail':'https://cdn.discordapp.com/emojis/695126170643071038.gif?v=1'
        },
        'frogs':{
            'op':False,
            'channel_rates':list()
        }
    }          
})


def fetch(db_guild, gid: int):
    # Returns the group settings of a guild
    #
    # @gid: the id of a guild
    #
    # @return: the configuration of {gid}
    query = db_guild.get(Query().id == gid)
    if query is None:
        initialize(db_guild, gid)
        query = db_guild.get(Query().id == gid)

    return query['groups']


def initialize(db_guild, gid: int):
    # Insert into the db a new posting for this guild id
    # DOES NOT CHECK IF THIS GUILD ID ALREADY EXISTS YET*
    #
    # @gid: the guild id
    guild = dict(guild_settings_default)
    guild['id'] = gid
    db_guild.insert(guild)


def write(db_guild, gid: int, settings: dict):
    # Overwrites a guild's current settings
    #
    # @gid: the guild id
    # @settings: a properly formatted 'groups', similar to 'default_settings'
    db_guild.update({'groups':settings}, Query().id == gid)


def upgrade(db_guild, gid: int):
    # Upgrades old group settings to a more current version
    #
    # @gid: the guild ids
    group = fetch(db_guild, gid)
    default_groups = guild_settings_default['groups']
    
    union_groups = set(group.keys()).union(default_groups.keys())
    for setting in union_groups:
        if setting not in group and setting in default_groups:
            group[setting] = default_groups[setting]
            continue
        elif setting in group and setting not in default_groups:
            group.pop(setting)
            continue
        
        unioned_fields = set(group[setting].keys()).union(default_groups[setting].keys())
        for field in unioned_fields:
            if field in default_groups[setting] and field not in group[setting]:
                group[setting][field] = default_groups[setting][field]
            elif field in group[setting] and field not in default_groups[setting]:
                group[setting].pop(field)
    
    write(db_guild, gid, group)
