import asyncio
import datetime
import hashlib
import json
import logging
import random
import re
import time

import aiosqlite
from aiogram.utils.markdown import quote_html
from python_socks import ProxyType
from telethon.helpers import _entity_type, _EntityType
from telethon.sessions.string import StringSession
from telethon.crypto import AuthKey

from .models import Settings, Account


logger = logging.getLogger(__name__)


async def relative_sleep(delay):
    delay = delay * 100
    third = delay / 3
    delay = random.randint(int(delay - third), int(delay + third)) / 100
    await asyncio.sleep(delay)


# def is_channel(group):
#     return _entity_type(group) == _EntityType.CHANNEL
#
#
# def sign_msg(text, sign='💥'):
#     return sign + ' ' + text
#
#
# def exc_to_msg(exception):
#     msg = re.sub(r'\(caused by \w+\)\s*$', '', str(exception))
#     return quote_html(msg)


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


def make_hash(string):
    # string = json.dumps(obj)
    return hashlib.md5(string.encode('utf8')).hexdigest()


# async def get_proxy():
    # res = []
    # with open('proxies.txt') as f:
    #     for line in f:
    #         line = line.strip()
    #         if line:
    #             url, creds = line.split(' ')
    #             addr, port = url.rsplit(':', 1)
    #             addr = addr.split('://')[-1]
    #             username, passwd = creds.rsplit(':', 1)
    #             proxy = {
    #                 'proxy_type': 'http',
    #                 'addr': addr,
    #                 'port': port,
    #                 'username': username,
    #                 'password': passwd
    #             }
    #             print(proxy)
    #             res.append(proxy)
    # return res
    # settings = await Settings.get_cached()
    # if settings.enable_proxy:
    #     return {
    #         'proxy_type': ProxyType.SOCKS5,
    #         'addr': '127.0.0.1',
    #         'port': 9050,
    #     }


# class TimeQueue(asyncio.Queue):
#
#     def put_nowait(self, item, delay=0):
#         item = (time.time() + delay, item)
#         super().put_nowait(item)
#
#     def get(self):
