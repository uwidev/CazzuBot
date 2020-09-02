# Manages the TinyDB database and ensures that data is written/read safely.

from tinydb import Query

class ReadOnlyDict(dict):
    # This class is meant to only allow a read-only dictionary. 
    # It does not prevent mutable values from being changed.
    #
    # This is to ensure that the factory default settings of a guild never gets changed.
    def __setitem__(self, key, value):
        raise TypeError('read-only dictionary, setting values is not supported')

    def __delitem__(self, key):
        raise TypeError('read-only dict, deleting values is not supported')

# Consider making this a class instead of a dictionary?
default_settings = ReadOnlyDict({
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
        }
    }          
})

def get_guild_conf(db, gid: int):
    # Returns the group settings of a guild
    #
    # @gid: the id of a guild
    #
    # @return: the configuration of {gid}
    query = db.get(Query().id == gid)
    if query is None:
        init_guild(db, gid)
        query = db.get(Query().id == gid)

    return query['groups']


def init_guild(db, gid: int):
    # Insert into the db a new posting for this guild id
    # DOES NOT CHECK IF THIS GUILD ID ALREADY EXISTS YET*
    #
    # @gid: the guild id
    guild_db = dict(default_settings)
    guild_db['id'] = id
    db.insert(guild_db)


def write_back_settings(db, gid: int, settings: dict):
    # Overwrites a guild's current settings
    #
    # @gid: the guild id
    # @settings: a properly formatted 'groups', similar to 'default_settings'
    db.update({'groups':settings}, Query().id == gid)


def update_settings(db, gid: int):
    # Upgrades old group settings to a more current version
    #
    # @gid: the guild ids
    group = get_guild_conf(db, gid)
    default_groups = default_settings['groups']
    
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
    
    write_back_settings(db, gid, group)
