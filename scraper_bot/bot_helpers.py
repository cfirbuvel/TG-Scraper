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
        time.sleep(0.5)



