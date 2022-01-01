import asyncio
import logging

from aiogram import Bot, Dispatcher, executor, types
# from aiogram.contrib.fsm_storage.redis import RedisStorage
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types.message import ParseMode

from .conf import Settings

logging.basicConfig(level=logging.INFO)

# storage = RedisStorage(host=redis_host, port=redis_port, db=redis_db)
settings = Settings()
bot = Bot(token=settings.token, parse_mode=ParseMode.HTML)
# TODO: Change to Redis storage
dispatcher = Dispatcher(bot, storage=MemoryStorage())
