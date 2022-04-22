import asyncio
import collections
import datetime
import itertools
import logging
from operator import itemgetter, attrgetter
import random
import time
from urllib.parse import urlsplit
from pprint import pprint

from aiogram.utils.exceptions import MessageNotModified
import aioitertools
from faker import Faker
import humanize
from more_itertools import first
from telethon.errors.rpcerrorlist import *
from telethon.sessions.string import StringSession
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.help import GetConfigRequest
from tortoise import timezone


from .bot import bot
from .models import Account, Group, Settings
from .client import CustomTelegramClient, GroupInvalidError
from .utils import relative_sleep, make_hash


logger = logging.getLogger(__name__)


class AccountInvitesEnd(Exception):
    pass


def user_valid(user):
    return not user.bot and not user.deleted


# settings = await Settings.get_cached()
#     filter = settings.last_seen
#     if filter:
#         return user_last_seen(user) <= filter
#     return True

# def user_last_seen(user):
#     days_ago = 365
#     status = user.status
#     if status:
#         name = status.to_dict()['_']
#         days_map = {
#             'UserStatusOnline': 0, 'UserStatusRecently': 1,
#             'UserStatusLastWeek': 7, 'UserStatusLastMonth': 30,
#         }
#         if name in days_map:
#             days_ago = days_map[name]
#     return days_ago

# async def update_name(client):
#    fake = Faker()
#    first_name = fake.first_name()
#    last_name = fake.last_name()
#    await client(UpdateProfileRequest(first_name=first_name, last_name=last_name))


# def sign_in(client, chat_id, items):
#     bot = dispatcher.bot
#     acc = client.account
#     code = None
#     while True:
#         try:
#             if code:
#                 await client.sign_in(acc.phone, code)
#                 return True
#             else:
#                 await client.send_code_request(acc.phone, force_sms=True)
#         except (ApiIdInvalidError, PhoneNumberBannedError, FloodWaitError, PhoneNumberUnoccupiedError) as e:
#             await bot.send_message(chat_id, exc_to_msg(e), disable_web_page_preview=True)
#             if type(e) in (ApiIdInvalidError, PhoneNumberBannedError):
#                 await acc.delete()
#                 await bot.send_message(chat_id, 'Account has been deleted.')
#             return
#         except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
#             msg = ('{}\n'
#                    'You can reenter code.\n'
#                    '<i>Keep in mind that after several attempts Telegram might'
#                    ' temporarily block account from signing in .</i>').format(exc_to_msg(e))
#         else:
#             msg = ('Code was sent to <b>{}</b>\n'
#                    'Please divide it with whitespaces, like: <i>41 9 78</i>').format(acc.safe_name)
#         await states.Scrape.enter_code.set()
#         await bot.send_message(chat_id, msg, reply_markup=keyboards.code_request())
#         answer = await items.get()
#         items.task_done()
#         if answer == 'resend':
#             code = None
#         elif answer == 'skip':
#             return
#         else:
#             code = answer

# async def on_group_error(error, group):
#     try:
#         raise error
#     except InviteHashExpiredError:
#         msg = 'Invite link has expired.'
#     except (InviteHashInvalidError, ChannelInvalidError, ChatIdInvalidError,
#             ChatInvalidError, PeerIdInvalidError, ValueError):
#         msg = 'Group doesn\'t exist or join link is not valid.'
#     except (ChatWriteForbiddenError, ChatAdminRequiredError):
#         msg = 'Adding users is not allowed.'
#     except IsBroadcastChannelError:
#         msg = 'It is broadcast channel and cannot be used.'
#     group.enabled = False
#     group.details = msg
#     await group.save()
#     msg = '♦️<i>{}</i> Error. {}'.format(group.get_name(), msg)
#     return msg

async def log_details(chat_id, stats, groups):
    line_width = 30
    sep = '⎺' * line_width
    start = stats['start_time']
    sent = []
    while True:
        msgs = []
        total_added = 0
        total_failed = 0
        msg = '<b>Groups</b>\n\n'
        for data in groups:
            group = data['obj']
            link = group.link
            name = group.name
            if not name:
                parts = urlsplit(link)
                name = parts.netloc + parts.path
            if len(name) > line_width:
                name = name[:27] + '...'
            total_added += data['users_added']
            total_failed += data['users_failed']
            block = ('<a href="{link}"><b>{name}</b></a>\n'
                     '<pre>'
                     '{status}\n'
                     'Accs:  {active: >4} active {joined: >4} joined\n')
            kicked = len(data['kicked'])
            if kicked:
                block += '       {: >4} kicked\n'.format(kicked)
            block += ('Users: {users_added: >4} added {users_failed: >5} failed\n'
                      '{sep}'
                      '</pre>\n')
            block = block.format(link=link, name=name, sep=sep, **data)
            if len(msg) + len(block) > 4096:
                msgs.append(msg)
                msg = ''
            msg += block
        msgs.append(msg)
        msg = ('<b>Overall</b>\n\n'
               '<pre>'
               'Accs:\n'
               '{active: >6} active {total: >9} total\n'
               '{finished: >6} finished {flood_wait: >7} flood\n'
               '{not_authed: >6} unauthed {deactivated: >7} banned\n'
               'Users:\n'
               '{total_added: >6} added {total_failed: >10} failed\n'
               '{sep}'
               '</pre>\n').format(sep=sep, total_added=total_added, total_failed=total_failed, **stats)
        msgs.append(msg)
        # loader = '▇▇▆▆▅▅▄▄▃▃▂▂▁▁'
        # frame = list(frame)
        # while True:
        #     yield ''.join(frame)
        #     frame.insert(0, frame.pop())
        # TODO: loader
        running_for = humanize.precisedelta(time.time() - start, minimum_unit='minutes', format='%d')
        logs = stats['logs']
        if logs:
            msg = '<b>Logs</b>\n\n'
            for entry in logs:
                entry = '<i>‣ {}</i>\n'.format(entry)
                if len(msg) + len(entry) > 4096:
                    msgs.append(msg)
                    msg = ''
                msg += entry
            msgs.append(msg)
        for i, msg in enumerate(msgs):
            hash = make_hash(msg)
            try:
                msg_id, prev_hash = sent[i]
            except IndexError:
                resp = await bot.send_message(chat_id, msg, disable_web_page_preview=True)
                sent.append((resp.message_id, hash))
            else:
                if hash == prev_hash:
                    continue
                resp = await bot.edit_message_text(msg, chat_id, msg_id, disable_web_page_preview=True)
                sent[i] = (resp.message_id, hash)
            await asyncio.sleep(1)
        await asyncio.sleep(0.4)


async def worker(accounts, groups, group_q, target_group, processed, lock: asyncio.Lock, stats):
    settings = await Settings.get_cached()
    for acc in accounts:
        # TODO: Maybe wrap block in a function again
        session = StringSession(acc.session_string)
        try:
            stats['active'] += 1
            async with CustomTelegramClient(session, acc.api_id, acc.api_hash) as client:
                if await client.is_user_authorized():
                    await client.clear_blocked()
                    logs = stats['logs']
                    try:
                        target = await client.join_group(target_group.link)
                    except ChannelPrivateError:
                        logs.append('<code>{}</code> banned from target group.'.format(acc.phone))
                        continue
                    if not target:
                        msg = '<b>Target group type or link is not valid.</b>'
                        if msg not in logs:
                            logs.append(msg)
                        return
                    async with lock:
                        if not processed:
                            temp = set()  # add all users to temporary set in case of UserDeactivatedBanError
                            offset = 0
                            while True:
                                # try:
                                users = await client.get_users(target, offset)
                                # except (UserDeactivatedBanError, UserBannedInChannelError, UserBlockedError, UserKickedError) as e:
                                #     logger.info(e)
                                #     return
                                if not users:
                                    break
                                for user in filter(user_valid, users):
                                    temp.add(user.id)
                                offset += len(users)
                                await relative_sleep(0.3)
                            processed.update(temp)
                    await relative_sleep(5)
                    acc_id = acc.id
                    while True:
                        if not any(item['status'] == 'Processing' for item in groups):
                            return
                        group = await group_q.get()
                        if acc_id in group['kicked']:
                            group_q.put_nowait(group)
                            continue
                        ts = group['join_ts']
                        wait = ts + settings.join_interval - time.time()
                        if wait > 0:
                            await relative_sleep(wait)
                        group_obj = group['obj']
                        try:
                            source = await client.join_group(group_obj.link)
                        except ChannelPrivateError:
                            group['kicked'].append(acc_id)
                            if all(acc_id in item['kicked'] for item in groups if item['status'] == 'Processing'):
                                logs.append('<code>{}</code> banned from all source groups.'.format(acc.phone))
                                break
                            group_q.put_nowait(group)
                            continue
                        if not source:
                            group['status'] = '❗ Invalid group type or link'
                            continue
                        group['join_ts'] = time.time()
                        group_obj.name = source.title
                        await group_obj.save()
                        group['active'] += 1
                        group['joined'] += 1
                        group_q.put_nowait(group)
                        offset = 0
                        # TODO: Store processed in database of kind
                        while True:
                            # try:
                            users = await client.get_users(source, offset, recent=settings.recent)
                            # except (UserDeactivatedBanError, UserBannedInChannelError, UserBlockedError, UserKickedError) as e:
                            #     logger.info(e)
                            #     return
                            if not users:
                                group['status'] = 'Over'
                                group['active'] -= 1
                                break
                                # TODO: Group status check in users loop and break on not "Active"? (if group users are same for every acc)
                            for user in users:
                                id = user.id
                                async with lock:
                                    if not user_valid(user) or id in processed:
                                        continue
                                    added = False
                                    try:
                                        resp = await client(InviteToChannelRequest(target, [user]))
                                    except (InputUserDeactivatedError, UserChannelsTooMuchError,
                                            UserNotMutualContactError, UserPrivacyRestrictedError):
                                        pass
                                    except PeerFloodError:
                                        await asyncio.sleep(random.randint(60, 120))
                                        continue
                                    # except FloodWaitError as ex:
                                        # TODO: logic for flood wait (end for now)
                                    else:
                                        added = len(resp.users)
                                    processed.add(id)
                                if added:
                                    group['users_added'] += 1
                                    acc.invites -= 1
                                    if not acc.invites:
                                        acc.sleep_until = timezone.now() + datetime.timedelta(days=settings.invites_reset_after)
                                        await acc.save()
                                        group['active'] -= 1
                                        stats['finished'] += 1
                                        raise AccountInvitesEnd()
                                    await acc.save()
                                else:
                                    group['users_failed'] += 1
                                await asyncio.sleep(random.randint(60, 120))
                            await relative_sleep(0.35)
                            offset += len(users)
                else:
                    stats['not_authed'] += 1
                    acc.authenticated = False
                    await acc.save()
        except UserDeactivatedBanError:
            stats['deactivated'] += 1
            acc.deactivated = True
            await acc.save()
        except FloodWaitError as ex:
            print('Debug FloodWaitError: {} seconds.'.format(ex.seconds))
            stats['flood_wait'] += 1
            acc.sleep_until = timezone.now() + datetime.timedelta(seconds=ex.seconds)
            await acc.save()
            # TODO
        except AccountInvitesEnd:
            pass
        finally:
            stats['active'] -= 1


async def main(chat_id):
    await bot.send_message(chat_id, 'Task started.')
    accounts = await Account.filter(deactivated=False, authenticated=True, invites__gt=0)
    sources = await Group.filter(enabled=True, is_target=False)
    target = await Group.get(is_target=True)
    # invites_max = sum(acc.invites for acc in accounts)
    stats = {
        'total': len(accounts), 'active': 0, 'finished': 0, 'flood_wait': 0,
        'not_authed': 0, 'deactivated': 0, 'logs': [], 'start_time': time.time()
    }
    groups = []
    group_q = asyncio.Queue()
    for group in sources:
        item = {
            'obj': group, 'status': 'Processing', 'active': 0, 'joined': 0,
            'kicked': [], 'users_failed': 0, 'users_added': 0, 'join_ts': 0
        }
        groups.append(item)
        group_q.put_nowait(item)
    accounts = iter(accounts)
    lock = asyncio.Lock()
    processed = set()
    num_workers = 18
    tasks = []
    for i in range(num_workers):
        task = asyncio.create_task(worker(accounts, groups, group_q, target, processed, lock, stats), name=str(i))
        tasks.append(task)
    log_task = asyncio.create_task(log_details(chat_id, stats, groups))
    tasks.append(log_task)
    await asyncio.gather(*tasks)


async def scrape(chat_id):
    try:
        await main(chat_id)
    except asyncio.CancelledError:
        await bot.send_message(chat_id, 'Task cancelled.')


async def show_loading(message):
    text = message.text
    async for sym in aioitertools.cycle('⬖⬘⬗⬙'):
        msg = '{} {}'.format(text, sym)
        print(msg)
        message = await message.edit_text(msg)
        await asyncio.sleep(1)
