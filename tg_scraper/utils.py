import asyncio
import logging
import re

import aiosqlite
from aiogram.utils.markdown import quote_html
from telethon.sessions.string import StringSession
from telethon.crypto import AuthKey


logger = logging.getLogger(__name__)


def sign_msg(text, sign='💥'):
    return sign + ' ' + text


def exc_to_msg(exception):
    msg = re.sub(r'\(caused by \w+\)\s*$', '', str(exception))
    return quote_html(msg)


def task_running(chat_id):
    name = str(chat_id)
    return any(task.get_name() == name for task in asyncio.all_tasks())


async def session_db_to_string(path):
    async with aiosqlite.connect(path) as db:
        try:
            c = await db.execute('select * from sessions')
        except aiosqlite.OperationalError:
            return
        row = await c.fetchone()
        await c.close()
        if row:
            obj = StringSession()
            obj._dc_id, obj._server_address, obj._port, key, obj._takeout_id = row
            obj._auth_key = AuthKey(data=key)
            return obj.save()


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
