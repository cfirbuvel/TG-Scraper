import redis
import json
import time
from configparser import ConfigParser
from peewee import SqliteDatabase


def read_config(config_name):
    config = ConfigParser()
    config.read(config_name)
    return config['Main']


def init_db(config_name):
    config = read_config(config_name)
    db_name = config['db_name']
    db = SqliteDatabase(db_name)
    return db




class SessionKeys:
    EXIT_THREAD = 1
    BOT_MSG = 2
    SCRAPER_MSG = 3
    RUNNING = 4




class JsonRedis(redis.StrictRedis):

    def json_get(self, name):
        value = self.get(name)
        if value:
            value = json.loads(value.decode("utf-8"))
        return value

    def json_set(self, name, value):
        value = json.dumps(value)
        return self.set(name, value)

    def clear_keys(self, *args):
        for key in args:
            self.json_set(key, None)


def get_redis_key(session, name):
    while True:
        value = session.json_get(name)
        if value:
            session.json_set(name, None)
            return value
        # if not value:
        #     exit = get_exit_key(session)
        #     if exit:
        #         return
        time.sleep(0.5)


def set_bot_msg(session, resp_enum, msg, keyboard_key=None):
    key = SessionKeys.BOT_MSG
    while True:
        exists = session.json_get(key)
        if not exists:
            session.json_set(key, (resp_enum, msg, keyboard_key))
            break
        else:
            time.sleep(0.5)


def set_exit_key(session):
    session.json_set(SessionKeys.EXIT_THREAD, True)


def get_exit_key(session):
    val = session.json_get(SessionKeys.EXIT_THREAD)
    session.clear_keys(SessionKeys.EXIT_THREAD)
    return val


def clear_session(session):
    session.clear_keys(SessionKeys.BOT_MSG, SessionKeys.SCRAPER_MSG, SessionKeys.EXIT_THREAD)




