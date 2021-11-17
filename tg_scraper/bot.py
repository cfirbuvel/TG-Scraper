import asyncio
from configparser import ConfigParser
import logging

from aiogram import Bot, Dispatcher, executor, types
# from aiogram.contrib.fsm_storage.redis import RedisStorage
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types.message import ParseMode


logging.basicConfig(level=logging.INFO)

config = ConfigParser()
config.read('config.ini')
config = config['Main']

# redis_host = config.get('Redis', 'host', fallback='localhost')
# redis_port = config.get('Redis', 'port', fallback='port')
# redis_db = config.get('Redis', 'db', fallback='db')
# storage = RedisStorage(host=redis_host, port=redis_port, db=redis_db)
lock = asyncio.Condition()

bot = Bot(token=config['bot_token'], parse_mode=ParseMode.HTML)
# TODO: Change to Redis storage
dp = Dispatcher(bot, storage=MemoryStorage())
