import asyncio
import configparser
import logging

from aiogram import Bot, Dispatcher, executor, types
# from aiogram.contrib.fsm_storage.redis import RedisStorage
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types.message import ParseMode


logging.basicConfig(level=logging.INFO)

config = configparser.ConfigParser()
config.read('config.ini')
# storage = RedisStorage(host=redis_host, port=redis_port, db=redis_db)
bot = Bot(token=config.get('main', 'bot_token'), parse_mode=ParseMode.HTML)
# TODO: Change to Redis storage
dispatcher = Dispatcher(bot, storage=MemoryStorage())
