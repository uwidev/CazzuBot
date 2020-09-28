# Manages the TinyDB database and ensures that data is written/read safely.

from tinydb import Query
from utility import ReadOnlyDict


BASE_EXP = 5


user_data_default = ReadOnlyDict({
    'id':None,
    'exp':0,
    'exp_factor':1,
    'frogs_lifetime':0,
    'frogs_normal':0,
    'frogs_frozen':0
})


def write(db_user, uid: int, data: dict):
    db_user.update(data, Query().id == uid)


def write_all(db_user, users):
    # would be faster to truncate then insert batch
    for user in users:
        write(db_user, user['id'], user)


def fetch(db_user, uid: int):
    query = db_user.get(Query().id == uid)
    if query is None:
        initialize(db_user, uid)
        query = db_user.get(Query().id == uid)
    
    return query


def fetch_all(db_user):
    return db_user.all()


def reset_exp_factor_all(db_user):
    db_user.update({'exp_factor':1.0})


def modify_exp(db_user, uid: int, exp: int):
    try:
        user = db_user.search(Query().id == uid)[0]
    except IndexError:
        user = dict(user_data_default)
        user['id'] = uid
    
    user['exp'] += exp * user['exp_factor']
    db_user.upsert(user, Query().id == uid)


def initialize(db_user, uid: int):
    user = dict(user_data_default)
    user['id'] = uid
    db_user.insert(user)


def upgrade(db_user):
    users_all = fetch_all(db_user)

    unioned_keys = set(users_all[0].keys()).union(user_data_default.keys())
    for user in users_all:
        for key in unioned_keys:
            if key not in user and key in user_data_default:
                user[key] = user_data_default[key]
                continue
            elif key in user and key not in user_data_default:
                user.pop(key)
                continue
    
    write_all(db_user, users_all)


def exchange_frogs_normal(db_user, user_id_from:int, user_id_to:int, amount:int):
    '''Moves normal frogs from one usesr to another. Has built in error checking for negative frogs.'''
    type = 'frogs_normal'
    user_from = fetch(db_user, user_id_from)
    user_to = fetch(db_user, user_id_to)

    if type not in user_from and type not in user_to:
        print(f'>> ERROR: Tried to exchange {amount} {type} from {user_id_from} to {user_id_to}. {type} doesn\'t exist as an attribute for users in database.')
        return -1
    
    if user_from[type] < amount:
        return 1

    user_from[type] -= amount
    user_to[type] += amount

    write(db_user, user_id_from, user_from)
    write(db_user, user_id_to, user_to)

    return 0