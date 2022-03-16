import asyncio
import datetime
import logging
import random
import re

import aiosqlite
from aiogram.utils.markdown import quote_html
from telethon.helpers import _entity_type, _EntityType
from telethon.sessions.string import StringSession
from telethon.crypto import AuthKey

from .models import Account


logger = logging.getLogger(__name__)


async def relative_sleep(delay):
    delay = delay * 100
    third = delay / 3
    delay = random.randint(int(delay - third), int(delay + third)) / 100
    await asyncio.sleep(delay)


def is_channel(group):
    return _entity_type(group) == _EntityType.CHANNEL


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


async def update_accounts_limits():
    await Account.filter(invites_reset_at__gte=datetime.datetime.now()).update(invites_sent=0)


def get_proxies():
    res = []
    with open('proxies.txt') as f:
        for line in f:
            line = line.strip()
            if line:
                url, creds = line.split(' ')
                addr, port = url.rsplit(':', 1)
                addr = addr.split('://')[-1]
                username, passwd = creds.rsplit(':', 1)
                proxy = {
                    'proxy_type': 'http',
                    'addr': addr,
                    'port': port,
                    'username': username,
                    'password': passwd
                }
                res.append(proxy)
    return res


class Queue(asyncio.Queue):

    def __deepcopy__(self, memo={}):
        return self
