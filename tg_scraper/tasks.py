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
import more_itertools
from telethon.errors.rpcerrorlist import *
from telethon.sessions.string import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.help import GetConfigRequest
from tortoise import timezone


from .bot import bot
from .models import Account, Group, Settings
from .client import CustomTelegramClient, GroupInvalidError
from .utils import relative_sleep, hash_object


logger = logging.getLogger(__name__)


class AccountInvitesEnd(Exception):
    pass


def user_valid(user):
    return not user.bot and not user.deleted

# def user_status_valid(user):
#     settings = await Settings.get_cached()
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


async def update_name(client):
    fake = Faker()
    first_name = fake.first_name()
    last_name = fake.last_name()
    await client(UpdateProfileRequest(first_name=first_name, last_name=last_name))


# async def sign_in(client, chat_id, items):
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
    messages = []
    while True:
        # new_hash = hash_object(stats)
        # if new_hash != stats_hash:
        #     stats_hash = new_hash
        total_added = 0
        # total_processed = 0
        msg = '<b>Groups</b>\n'
        for data in groups:
            link = data['link']
            name = urlsplit(data['link']).path.strip('/')
            status = data['status']
            active = data['active']
            joined = data['joined']
            kicked = len(data['kicked'])
            added = data['users_added']
            total_added += added
            processed = data['users_processed']
            # total_processed += processed
            text = (f'\n<a href="{link}"><b>{name}</b></a>      [ {status} ]\n'
                    f'<b>{active}</b> active accounts, <b>{joined}</b> joined, <b>{kicked}</b> kicked\n'
                    f'<b>{processed}</b> users processed, <b>{added}</b> added')
            msg += text
        msg += ('\n\n<b>Total</b>\n\n'
                '<b>{total}</b> accounts total, <b>{active}</b> active, <b>{finished}</b> finished\n'
                '<b>{not_authed}</b> not authenticated, <b>{deactivated}</b> deactivated\n\n'
                '<b>{total_added}</b> users added').format(total_added=total_added, **stats)
        logs = '<b>Logs</b>\n\n' + '\n'.join(stats['logs'])
        try:
            if not messages:
                messages.append(await bot.send_message(chat_id, msg, disable_web_page_preview=True))
                await relative_sleep(1)
                messages.append(await bot.send_message(chat_id, logs, disable_web_page_preview=True))
            else:
                await messages[0].edit_text(msg, disable_web_page_preview=True)
                await relative_sleep(1)
                await messages[1].edit_text(logs, disable_web_page_preview=True)
        except MessageNotModified:  # FIXME
            pass
        await relative_sleep(2.5)  # 0.55 per message
    # while True:
    #     accounts = []
    #     for phone, stats in stats['accounts'].items():
    #         total_added = stats['added']
    #         total_added += total_added
    #         # TODO: Int statuses for elaborate total stats
    #         log = '<b>{}:</b> ⌞{}⌟ {}/{} added'.format(phone, stats['status'], total_added, stats['max'])
    #         accounts.append(log)
    #     groups = []
    #     for stats in stats['groups'].items():
    #         log = '<b>{link}:</b> ⌞{status}⌟ {users_added}/{users} added, {joined} accounts joined, {kicked} kicked'.format(**stats)
    #         groups.append(log)
    #     accounts = '\n'.join(accounts)
    #     if not accounts_msg:
    #         accounts_msg = await bot.send_message(chat_id, accounts)
    #     else:
    #         await accounts_msg.edit_text(accounts)
    #     groups = '\n'.join(groups)
    #     if not groups_msg:
    #         groups_msg = await bot.send_message(chat_id, groups)
    #     else:
    #         await groups_msg.edit_text(groups)
    #     await asyncio.sleep(1)


async def worker(accounts, groups, target_group, processed, lock: asyncio.Lock, stats):
    settings = await Settings.get_cached()
    for acc in accounts:
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
                        logs.append('`{}` banned from target group.'.format(acc.phone))
                        continue
                    except GroupInvalidError as ex:
                        msg = '⚠ <b>Target group:</b> {}.'.format(ex.msg)
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
                        if not groups:
                            return
                        try:
                            data = more_itertools.first(filter(lambda x: acc_id not in x[1]['kicked'], groups))
                        except ValueError:
                            logs.append('✕ `{}` banned from all source groups.'.format(acc.phone))
                            break
                        join_reset, group = data
                        data[0] = max(join_reset, time.time()) + settings.join_interval
                        groups.sort(key=itemgetter(0))
                        wait_secs = join_reset - time.time()
                        if wait_secs > 0:
                            await relative_sleep(wait_secs)
                        try:
                            source = await client.join_group(group['link'])
                        except ChannelPrivateError:
                            group['kicked'].append(acc_id)
                            continue
                        except GroupInvalidError as ex:
                            groups.remove(data)
                            group['status'] = '⚠ {}'.format(ex.msg)
                            continue
                        else:
                            group['active'] += 1
                            group['joined'] += 1
                        offset = 0
                        # TODO: Store processed in database of kind
                        while True:
                            # try:
                            users = await client.get_users(source, offset, recent=settings.recent)
                            # except (UserDeactivatedBanError, UserBannedInChannelError, UserBlockedError, UserKickedError) as e:
                            #     logger.info(e)
                            #     return
                            if not users:
                                groups.remove(data)
                                group['status'] = 'Processed'
                                group['active'] -= 1
                                break
                                # TODO: Group status check in users loop and break on not "Active"? (if group users are same for every acc)
                                # if all(item['status'] != 'Active' for item in groups):
                                #     return
                            for user in users:
                                id = user.id
                                async with lock:
                                    if not user_valid(user) or id in processed:
                                        continue
                                    try:
                                        resp = await client(InviteToChannelRequest(target, [user]))
                                    except (InputUserDeactivatedError, UserChannelsTooMuchError,
                                            UserNotMutualContactError, UserPrivacyRestrictedError,
                                            PeerFloodError):
                                        added = False
                                    # except FloodWaitError as ex:
                                        # TODO: logic for flood wait (end for now)
                                        # await asyncio.sleep(ex.seconds)
                                        # continue
                                    else:
                                        added = bool(resp.users)
                                    processed.add(id)
                                if added:
                                    group['users_added'] += 1
                                    acc.invites -= 1
                                    if not acc.invites:
                                        acc.sleep_until = timezone.now() + datetime.timedelta(days=settings.invites_reset_after)
                                        await acc.save()
                                        group['active'] -= 1
                                        raise AccountInvitesEnd()
                                    await acc.save()
                                        # TODO: Batch invite?
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
            stats['flood_wait'] += 1
            acc.sleep_until = timezone.now() + datetime.timedelta(seconds=ex.seconds)
            await acc.save()
            # TODO
        except AccountInvitesEnd:
            stats['finished'] += 1
        finally:
            stats['active'] -= 1


async def scrape(chat_id):
    await bot.send_message(chat_id, 'Task started. You can stop it at any moment with /stop command.')
    accounts = await Account.filter(deactivated=False, authenticated=True, invites__gt=0)
    sources = await Group.filter(enabled=True, is_target=False)
    target = await Group.get(is_target=True)
    # invites_max = sum(acc.invites for acc in accounts)
    stats = {
        'total': len(accounts), 'active': 0, 'finished': 0, 'not_authed': 0,
        'deactivated': 0, 'flood_wait': 0, 'logs': []
    }
    groups = []
    groups_q = []
    for group in sources:
        item = {
            'link': group.link, 'status': 'Active', 'active': 0, 'joined': 0,
            'kicked': [], 'users_processed': 0, 'users_added': 0
        }
        groups.append(item)
        groups_q.append([0, item])
    # stats['groups'] = all_groups
    accounts = iter(accounts)
    lock = asyncio.Lock()
    processed = set()
    num_workers = 16
    tasks = []
    for i in range(num_workers):
        task = asyncio.create_task(worker(accounts, groups_q, target, processed, lock, stats), name=str(i))
        tasks.append(task)
    log_task = asyncio.create_task(log_details(chat_id, stats, groups))
    tasks.append(log_task)
    res = await asyncio.gather(*tasks)

            # parts.append(text)
        # msg = '\n⎻⎻⎻⎻⎻⎻⎻⎻⎻⎻⎻⎻⎻⎻\n'.join(parts)
    # log_task = asyncio.create_task(run_log(chat_id, stats))
    # await asyncio.gather(log_task, *tasks)


# async def scrape(chat_id, items: asyncio.Queue):
#     bot = dispatcher.bot
#     await bot.send_message(chat_id, 'Task started. You can stop it at any moment with /stop command.')
#     accounts = list(await Account.filter(auto_created=True, invites_sent__lt=F('invites_max')))
#     max_invites = sum(acc.invites_left for acc in accounts)
#     accs_loaded = len(accounts)
#     await states.Scrape.add_limit.set()
#     msg = 'Please enter max number of users to add, <b>{} max</b>.'.format(max_invites)
#     await bot.send_message(chat_id, msg, reply_markup=keyboards.max_btn(max_invites))
#     limit = await items.get()
#     items.task_done()
#     limit = min(max_invites, limit)
#     target = await Group.get(is_target=True)
#     sources = await Group.filter(enabled=True, is_target=False)
#     state = RunState(limit)
#     tasks = []
#     task_name = str(chat_id)
#     for group in sources:
#         task = asyncio.create_task(worker(accounts, target, group, state, settings), name=task_name)
#         tasks.append(task)
#     animation = animation_frames()
#     logs = []
#     message = None
#     while tasks:
#         done, tasks = await asyncio.wait(tasks, timeout=1, return_when=asyncio.FIRST_COMPLETED)
#         for task in done:
#             msg = task.result()
#             if msg and msg not in logs:
#                 logs.append(msg)
#         if not tasks:
#             status = '☘ Completed ☘'
#         else:
#             status = 'Running tasks'
#         msg = ('<b>{status}</b>\n\n'
#                'Tasks (groups): {tasks}\n'
#                'Sessions: {accs_used}/{accs_total}\n'
#                'Users processed: {processed}\n'
#                'Users added: {added}\n\n'
#                '{loading}\n\n'
#                '<i>Logs:</i>\n\n'
#                '{logs}\n').format(
#             status=status,
#             tasks=len(tasks),
#             accs_used=accs_loaded - len(accounts),
#             accs_total=accs_loaded,
#             processed=len(state.users_processed),
#             added=state.added,
#             loading=next(animation),
#             logs='\n'.join(logs)
#         )
#         if not message:
#             message = await bot.send_message(chat_id, msg, disable_web_page_preview=True)
#         else:
#             message = await message.edit_text(msg, disable_web_page_preview=True)
#     await states.Menu.main.set()
#     await bot.send_message(chat_id, 'Main', reply_markup=keyboards.main_menu())
#     # TODO: Cancel handler with message


def animation_frames():
    frame = '▂▂▃▃▄▄▅▅▆▆▇▇██▇▇▆▆▅▅▄▄▃▃▂▂▁▁'
    frame = list(frame)
    while True:
        yield ''.join(frame)
        frame.insert(0, frame.pop())


async def show_loading(message):
    text = message.text
    async for sym in aioitertools.cycle('⬖⬘⬗⬙'):
        msg = '{} {}'.format(text, sym)
        print(msg)
        message = await message.edit_text(msg)
        await asyncio.sleep(1)
