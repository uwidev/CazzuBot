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