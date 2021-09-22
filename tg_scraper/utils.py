import asyncio
import itertools
import logging
import re

from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters import Filter, StateFilter
from aiogram.types import CallbackQuery
from telethon import TelegramClient
from telethon.sessions.string import StringSession
from tortoise import run_async

logger = logging.getLogger(__name__)


class QueryDataFilter(Filter):

    def __init__(self, *args):
        self.data = list(args)

    async def check(self, callback_query):
        return callback_query.data in self.data


# class TaskRunning(Filter):
#
#     async def check(self, obj):
#         if type(obj) == CallbackQuery:
#             obj = obj.message
#         task_name = str(obj.chat.id)
#         return any(task.get_name() == task_name for task in asyncio.all_tasks())


def sign_msg(text, sign='💥'):
    return sign + ' ' + text


def tg_error_msg(exception):
    msg = re.sub(r'\(caused by \w+\)\s*$', '', str(exception))
    return msg


def task_running(chat_id):
    name = str(chat_id)
    return any(task.get_name() == name for task in asyncio.all_tasks())


class TgClient(TelegramClient):

    def __init__(self, account, *args, **kwargs):
        self.account = account
        session = StringSession(string=account.session_string)
        # session = AccountSession(account)
        super().__init__(session, account.api_id, account.api_hash, *args, **kwargs)

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


class Queue(asyncio.Queue):

    def __deepcopy__(self, memo={}):
        return self


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
