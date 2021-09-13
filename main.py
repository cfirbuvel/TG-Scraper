import asyncio

from aiogram import executor
from tortoise import run_async

from tg_scraper.bot import dp
from tg_scraper.handlers import *
from tg_scraper.models import init_db


# async def tear_down():
#     await dp.storage.close()
#     await dp.storage.wait_closed()

# async def run(reset_webhook=None, timeout=20, relax=0.1, fast=True, allowed_updates=None):
#     await init_db()

def on_start(dispatcher):
    run_async(init_db())


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True)
    # loop = asyncio.get_event_loop()
    # asyncio.run(init_db())
    # executor.start_polling(dp, skip_updates=True)
