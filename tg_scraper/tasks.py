import asyncio
from collections import defaultdict, OrderedDict
from contextlib import AsyncExitStack
import datetime
import itertools
import logging
import math
import random
import re
import time

import aioitertools
from faker import Faker
import more_itertools
from telethon import connection
from telethon.errors.rpcerrorlist import *
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantsRequest, JoinChannelRequest, \
    LeaveChannelRequest, DeleteChannelRequest, GetParticipantRequest
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.functions.messages import AddChatUserRequest, GetFullChatRequest, ImportChatInviteRequest, \
    CheckChatInviteRequest, DeleteChatUserRequest, DeleteChatRequest
from telethon.tl.types import InputPhoneContact, ChannelParticipantsSearch, ChatInviteAlready
from telethon.tl.types import Chat, Channel, ChatFull
from tortoise.expressions import F


from . import keyboards
from .bot import dispatcher
from .conf import settings
from .models import Account, Group
from .states import Menu, Scrape
from .tg import TgClient, IsBroadcastChannelError
from .utils import exc_to_msg, relative_sleep


logger = logging.getLogger(__name__)


class RunState:

    def __init__(self, limit):
        self.limit = limit
        self.added = 0
        self.users_processed = set()

    @property
    def limit_reached(self):
        return self.added >= self.limit


def user_valid(user):
    return not any([user.bot, user.deleted, user.scam]) and user_status_valid(user)


def user_status_valid(user):
    filter = settings.last_seen_filter
    if filter:
        last_seen = user_last_seen(user)
        if last_seen is not None:
            return last_seen <= filter
        return False
    return True


def user_last_seen(user):
    days_ago = 365
    status = user.status
    if status:
        name = status.to_dict()['_']
        days_map = {
            'UserStatusOnline': 0, 'UserStatusRecently': 1,
            'UserStatusLastWeek': 7, 'UserStatusLastMonth': 30,
        }
        if name in days_map:
            days_ago = days_map[name]
    return days_ago


async def update_name(client):
    fake = Faker()
    first_name = fake.first_name()
    last_name = fake.last_name()
    await client(UpdateProfileRequest(first_name=first_name, last_name=last_name))


async def sign_in(client, chat_id, queue):
    bot = dispatcher.bot
    acc = client.account
    code = None
    while True:
        try:
            if code:
                await client.sign_in(acc.phone, code)
                return True
            else:
                await client.send_code_request(acc.phone, force_sms=True)
        except (ApiIdInvalidError, PhoneNumberBannedError, FloodWaitError, PhoneNumberUnoccupiedError) as e:
            await bot.send_message(chat_id, exc_to_msg(e), disable_web_page_preview=True)
            if type(e) in (ApiIdInvalidError, PhoneNumberBannedError):
                await acc.delete()
                await bot.send_message(chat_id, 'Account has been deleted.')
            return
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
            msg = ('{}\n'
                   'You can reenter code.\n'
                   '<i>Keep in mind that after several attempts Telegram might'
                   ' temporarily block account from signing in .</i>').format(exc_to_msg(e))
        else:
            msg = ('Code was sent to <b>{}</b>\n'
                   'Please divide it with whitespaces, like: <i>41 9 78</i>').format(acc.safe_name)
        await Scrape.enter_code.set()
        await bot.send_message(chat_id, msg, reply_markup=keyboards.code_request())
        answer = await queue.get()
        queue.task_done()
        if answer == 'resend':
            code = None
        elif answer == 'skip':
            return
        else:
            code = answer


async def on_group_error(error, group):
    try:
        raise error
    except InviteHashExpiredError:
        msg = 'Invite link has expired.'
    except (InviteHashInvalidError, ChannelInvalidError, ChatIdInvalidError,
            ChatInvalidError, PeerIdInvalidError, ValueError):
        msg = 'Group doesn\'t exist or join link is not valid.'
    except (ChatWriteForbiddenError, ChatAdminRequiredError):
        msg = 'Adding users is not allowed.'
    except IsBroadcastChannelError:
        msg = 'It is broadcast channel and cannot be used.'
    group.enabled = False
    group.details = msg
    await group.save()
    msg = '♦️<i>{}</i> Error. {}'.format(group.get_name(), msg)
    return msg


async def worker(accounts, group_to, group_from, state: RunState):
    # TODO: MAke sure settings refresh if changed when task running
    while accounts:
        acc = accounts.pop(0)
        start = time.time()
        try:
            async with TgClient(acc, store_session=False, proxy=settings.proxy) as client:
                if not await client.is_user_authorized():
                    logger.info('Account %s is not authenticated. Deleting from db.', acc.name)
                    await acc.delete()
                    continue
                await update_name(client)
                await client.clear_channels(free_slots=2)
                await client.clear_blocked()
                try:
                    to = await client.join_group(group_to.link)
                except (ChannelPrivateError, UsernameInvalidError):
                    continue
                except (InviteHashExpiredError, InviteHashInvalidError,
                        ChannelInvalidError, IsBroadcastChannelError, ValueError) as err:
                    return await on_group_error(err, group_to)
                await relative_sleep(5)
                try:
                    from_ = await client.join_group(group_from.link)
                except (ChannelPrivateError, UsernameInvalidError):
                    accounts.append(acc)
                    continue
                except (InviteHashExpiredError, InviteHashInvalidError,
                        ChannelInvalidError, IsBroadcastChannelError, ValueError) as err:
                    accounts.append(acc)
                    return await on_group_error(err, group_from)
                try:
                    users = await client.get_participants(from_)
                except (ChatAdminRequiredError) as err:
                    return await on_group_error(err, from_)
                group_from.users_count = len(users)
                await group_from.save()
                for user in filter(user_valid, users):
                    user_id = user.id
                    if user_id in state.users_processed:
                        continue
                    try:
                        # TODO: exception handling and checking if invite success
                        res = await client.invite_to_group(user, to)
                    # TODO: Check if all exceptions present
                    except (ChannelInvalidError, ChatIdInvalidError, ChatInvalidError, PeerIdInvalidError,
                            ChatAdminRequiredError) as err:
                        return await on_group_error(err, group_to)
                    except (InputUserDeactivatedError, UserBannedInChannelError, UserChannelsTooMuchError,
                            UserKickedError, UserPrivacyRestrictedError, UserIdInvalidError,
                            UserNotMutualContactError, UserAlreadyParticipantError):
                        pass
                    except (ChannelPrivateError, ChatWriteForbiddenError):
                        break
                    except PeerFloodError:
                        await relative_sleep(20)
                    else:
                        await acc.incr_invites()
                        state.added += 1
                        if state.limit_reached:
                            return
                    state.users_processed.add(user_id)
                    if not acc.can_invite:
                        dt = datetime.datetime.now() + datetime.timedelta(days=settings.limit_reset)
                        acc.invites_reset_at = dt
                        await acc.save()
                        break
                    await relative_sleep(8)
                else:
                    msg = '🔷 <i>{}</i> group has been processed.'.format(group_from.name)
                    return msg
                end = time.time()
                delay = settings.join_delay - (end - start)
                if delay > 0:
                    await relative_sleep(delay)
        except AuthKeyDuplicatedError:
            logger.info('Account %s cannot be used anymore.', acc.name)
            # await client.save_session()
        except UserDeactivatedBanError:
            logger.info('Account %s has been banned. Deleting from db.', acc.name)
            await acc.delete()


async def scrape(chat_id, queue: asyncio.Queue):
    bot = dispatcher.bot
    await bot.send_message(chat_id, 'Task started. You can stop it at any moment with /stop command.')
    accounts = list(await Account.filter(auto_created=True, invites_sent__lt=F('invites_max')))
    max_invites = sum(acc.invites_left for acc in accounts)
    await Scrape.add_limit.set()
    msg = 'Please enter max number of users to add, <b>{} max</b>.'.format(max_invites)
    await bot.send_message(chat_id, msg, reply_markup=keyboards.max_btn(max_invites))
    limit = await queue.get()
    queue.task_done()
    limit = min(max_invites, limit)
    accs_loaded = len(accounts)
    target = await Group.get(is_target=True)
    sources = await Group.filter(enabled=True, is_target=False)
    state = RunState(limit)
    tasks = []
    task_name = str(chat_id)
    for group in sources:
        task = asyncio.create_task(worker(accounts, target, group, state), name=task_name)
        tasks.append(task)
    animation = animation_frames()
    logs = []
    message = None
    while tasks:
        done, tasks = await asyncio.wait(tasks, timeout=1, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            msg = task.result()
            if msg and msg not in logs:
                logs.append(msg)
        if not tasks:
            status = '☘ Completed ☘'
        else:
            status = 'Running tasks'
        msg = ('<b>{status}</b>\n\n'
               'Tasks (groups): {tasks}\n'
               'Sessions: {accs_used}/{accs_total}\n'
               'Users processed: {processed}\n'
               'Users added: {added}\n\n'
               '{loading}\n\n'
               '<i>Logs:</i>\n\n'
               '{logs}\n').format(
            status=status,
            tasks=len(tasks),
            accs_used=accs_loaded - len(accounts),
            accs_total=accs_loaded,
            processed=len(state.users_processed),
            added=state.added,
            loading=next(animation),
            logs='\n'.join(logs)
        )
        if not message:
            message = await bot.send_message(chat_id, msg)
        else:
            message = await message.edit_text(msg)
    await Menu.main.set()
    await bot.send_message(chat_id, 'Main', reply_markup=keyboards.main_menu())
    # TODO: Cancel handler with message


def animation_frames():
    frame = '▂▃▄▅▆▇█▇▆▅▄▃▂▁'
    frame = list(frame)
    while True:
        yield ''.join(frame)
        frame.insert(0, frame.pop())


# async def scrape_repeatedly(chat_id, queue: asyncio.Queue):
#     interval = 86400
#     bot = dispatcher.bot
#     await bot.send_message(chat_id, 'Task started. You can stop it at any moment with /stop command.')
#     loading_task = None
#     master = None
#     clients = []
#     tasks = []
#     try:
#         settings = Settings()
#         # skip_sign_in = settings.skip_sign_in
#         proxy = settings.proxy
#         while True:
#             users_added = set()
#             if not master:
#                 for acc in await Account.filter(auto_created=False):
#                     await acc.refresh_invites()
#                     if acc.can_invite:
#                         await bot.send_message(chat_id, 'Initializing account <b>{}</b>'.format(acc.safe_name))
#                         master = TgClient(acc, proxy=proxy)
#                         await master.connect()
#                         if await master.is_user_authorized() or await sign_in(master, chat_id, queue):
#                             break
#                         await bot.send_message(chat_id, 'Skipping account')
#                         await master.save_session()
#                         await master.disconnect()
#                         master = None
#                         await asyncio.sleep(1)
#                 if not master:
#                     await bot.send_message(chat_id, 'No accounts available now. Stopping.')
#                     break
#                 groups = {}
#                 async for dialog in master.iter_dialogs():
#                     if dialog.is_group:
#                         num_participants = dialog.entity.participants_count
#                         groups[str(dialog.id)] = (dialog.title[:50], num_participants)
#                 if len(groups) < 2:
#                     msg = 'Main/first account should be a member of at least 2 groups (source and group_to).'
#                     await bot.send_message(chat_id, msg)
#                     break
#                 rows = [(key, tracker[0]) for key, tracker in groups.items()]
#                 queue.put_nowait(rows)
#                 await Scrape.select_group.set()
#                 reply_markup = keyboards.groups_list(rows)
#                 await bot.send_message(chat_id, '<b>Choose a group to add users to</b>', reply_markup=reply_markup)
#                 await queue.join()
#                 to_id = await queue.get()
#                 queue.task_done()
#                 del groups[to_id]
#                 to_id = int(to_id)
#                 rows = [(key, '{} ({})'.format(*tracker)) for key, tracker in groups.items()]
#                 queue.put_nowait(rows)
#                 await Scrape.select_multiple_groups.set()
#                 reply_markup = keyboards.multiple_groups(rows)
#                 await bot.send_message(chat_id, '<b>Select groups to scrape users from</b>', reply_markup=reply_markup)
#                 await queue.join()
#                 from_ids = [int(item) for item in await queue.get()]
#                 queue.task_done()
#             msg = await bot.send_message(chat_id, 'Adding users')
#             loading_task = asyncio.create_task(show_loading(msg))
#             # async for user in aggressive_iter(master.iter_participants(to_id, aggressive=True)):
#             async for user in get_participants(master, to_id):
#                 if user_active(user):
#                     users_added.add(user.id)
#             group_counts = {}
#             for group_id in from_ids:
#                 count = 0
#                 async for user in get_participants(master, group_id):
#                 # async for user in aggressive_iter(master.iter_participants(group_id, aggressive=True)):
#                     if user_active(user) and user.id not in users_added:
#                         count += 1
#                 if count:
#                     group_counts[group_id] = count
#             from_ids = list(group_counts.keys())
#             # TODO: Messages when no users to add or no groups selected
#             await update_name(master)
#             master_user = await master.get_me()
#             to_group = await master.get_entity(to_id)
#             lock = asyncio.Lock()
#             j = 0
#             for acc in await Account.filter(auto_created=True):
#                 if not from_ids:
#                     break
#                 await acc.refresh_invites()
#                 if acc.can_invite:
#                     client = TgClient(acc, proxy=proxy)
#                     clients.append(client)  # to clear connection in case of cancel in the middle of code below
#                     await client.connect()
#                     if await client.is_user_authorized():
#                         user = await client.get_me()
#                         logger.error('Deleted: %s', user.deleted)
#                         if not user.deleted:
#                             await update_name(client)
#                             phone_contact = InputPhoneContact(client_id=user.id, phone=user.phone,
#                                                               first_name=user.first_name or '', last_name=user.last_name or '')
#                             try:
#
#                                 await master(ImportContactsRequest([phone_contact]))
#                             except UserDeactivatedBanError:
#                                 clients.pop()
#                                 logger.error('Deleting account {}'.format(acc.name))
#                                 await acc.delete()
#                                 await client.disconnect()
#                                 continue
#                             phone_contact = InputPhoneContact(client_id=master_user.id, phone=master_user.phone,
#                                                               first_name=master_user.first_name or '',
#                                                               last_name=master_user.last_name or '')
#                             await client(ImportContactsRequest([phone_contact]))
#                             passed = False
#                             while True:
#                                 j = j % len(from_ids)
#                                 try:
#                                     from_id = from_ids[j]
#                                 except IndexError:
#                                     break
#                                 from_group = await master.get_entity(from_id)
#                                 try:
#                                     await add_to_group(master, from_group, user.id)
#                                 except (UserKickedError, UserDeactivatedBanError, UserBannedInChannelError,
#                                         UserChannelsTooMuchError, InputUserDeactivatedError, UserBlockedError) as e:
#                                     logger.info(str(e))
#                                     logger.info('Skipping client.')
#                                     break
#                                 except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
#                                     logger.info(str(e))
#                                     logger.info('Skipping group.')
#                                     del from_ids[j]
#                                     del group_counts[from_id]
#                                     continue
#                                 await master.account.incr_invites()
#                                 try:
#                                     await add_to_group(master, to_group, user.id)
#                                 except (UserKickedError, UserDeactivatedBanError, UserBannedInChannelError,
#                                         UserChannelsTooMuchError, InputUserDeactivatedError, UserBlockedError) as e:
#                                     logger.info(str(e))
#                                     logger.info('Skipping client.')
#                                     break
#                                 except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
#                                     msg = exc_to_msg(e)
#                                     await bot.send_message(chat_id, msg)
#                                     raise asyncio.CancelledError()
#                                 await master.account.incr_invites()
#                                 count = group_counts[from_id]
#                                 count -= acc.invites_left
#                                 task = asyncio.create_task(add_users(client, from_id, to_id, users_added, lock))
#                                 tasks.append(task)
#                                 if count > 0:
#                                     group_counts[from_id] = count
#                                     j += 1
#                                 else:
#                                     del from_ids[j]
#                                     del group_counts[from_id]
#                                 passed = True
#                                 break
#                             if passed:
#                                 await asyncio.sleep(10)
#                             else:
#                                 clients.pop()
#                                 await client.disconnect()
#                             if not master.account.can_invite:
#                                 master.account.invites_reset_at = datetime.datetime.now() + datetime.timedelta(seconds=interval)
#                                 await master.account.save()
#                                 break
#                             continue
#                     logger.error('Deleting account {}'.format(acc.name))
#                     clients.pop()
#                     await acc.delete()
#                     await client.disconnect()
#             if tasks:
#                 await asyncio.gather(*tasks)
#                 tasks = []
#             while clients:
#                 client = clients.pop()
#                 await client.save_session()
#                 await client.disconnect()
#             loading_task.cancel()
#             await loading_task
#             await bot.send_message(chat_id, 'Users added.')
#             wait_until = datetime.datetime.now() + datetime.timedelta(seconds=interval)
#             msg = 'Next scrape will start at {}.'.format(wait_until.strftime('%d-%m-%Y %H:%M'))
#             await bot.send_message(chat_id, msg)
#             await asyncio.sleep(interval)
#     except asyncio.CancelledError:
#         if loading_task and not loading_task.done():
#             loading_task.cancel()
#             await loading_task
#         for task in tasks:
#             if not task.done():
#                 task.cancel()
#         for client in clients:
#             await client.save_session()
#             await client.disconnect()
#         if tasks:
#             await asyncio.gather(*tasks)
#         await bot.send_message(chat_id, 'Run stopped.')
#     if master:
#         await master.save_session()
#         await master.disconnect()
#     await Menu.main.set()
#     await bot.send_message(chat_id, 'Main', reply_markup=keyboards.main_menu())

# def animation():


async def show_loading(message):
    text = message.text
    async for sym in aioitertools.cycle('⬖⬘⬗⬙'):
        msg = '{} {}'.format(text, sym)
        message = await message.edit_text(msg)
        await asyncio.sleep(1)
