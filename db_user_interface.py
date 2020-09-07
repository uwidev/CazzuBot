# Manages the TinyDB database and ensures that data is written/read safely.

from tinydb import Query
from utility import ReadOnlyDict


BASE_EXP = 5


user_data_default = ReadOnlyDict({
    'id':None,
    'exp':0,
    'exp_factor':1,
    'frogs':0,
    'frozen_frogs':0
})


def write(db_user, uid: int, data: dict):
    db_user.update(data, Query().id == uid)


def fetch(db_user, uid: int):
    query = db_user.get(Query().id == uid)
    if query is None:
        initialize(db_user, uid)
        query = db_user.get(Query().id == uid)
    
    return query


def modify_exp(db_user, uid: int, exp: int):
    try:
        user = db_user.search(Query().id == uid)[0]
    except IndexError:
        user = dict(user_data_default)
        user['id'] = uid

    
    user['exp'] += exp
    db_user.upsert(user, Query().id == uid)


def initialize(db_user, uid: int):
    user = dict(user_data_default)
    user['id'] = uid
    db_user.insert(user)