import asyncio
import itertools
import logging

from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters import Filter, StateFilter
from aiogram.types import CallbackQuery
from telethon import TelegramClient
from telethon.sessions.string import StringSession
from tortoise import run_async

logger = logging.getLogger(__name__)


def callback_query_filter(*callback_data):
    callback_data = list(callback_data)

    def actual_filter(update):
        return type(update) == CallbackQuery and update.data in callback_data

    return actual_filter


async def wait_for_state_value(state, key, timeout=86400):
    sleep_for = 0.3
    while True:
        try:
            return (await state.get_data())[key]
        except KeyError:
            await asyncio.sleep(sleep_for)
            timeout -= sleep_for
            if timeout <= 0:
                raise TimeoutError('Timeout exceeded.')


class TgClient(TelegramClient):

    def __init__(self, account, *args, **kwargs):
        self.account = account
        session = StringSession(string=account.session_string)
        # session = AccountSession(account)
        super().__init__(session, account.api_id, account.api_hash)

    async def save_session(self):
        session_string = self.session.save()
        self.account.session_string = session_string
        await self.account.save()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.save_session()
        await self.disconnect()


# # TODO: Change to Redis storage
# class Storage(MemoryStorage):
#
#     async def wait_for_value(self, key, timeout=86400):
#         sleep_for = 0.3
#         while True:
#             data = await self.get_data()
#             try:
#                 return data[key]
#             except KeyError:
#                 await asyncio.sleep(sleep_for)
#                 timeout -= sleep_for
#                 if timeout <= 0:
#                     raise TimeoutError('Timeout exceeded.')
