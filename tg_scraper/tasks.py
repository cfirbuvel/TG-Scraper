import asyncio
from collections import defaultdict, OrderedDict
from contextlib import AsyncExitStack
import datetime
import itertools
import logging
import math
import random

from aiogram.bot.bot import Bot
from aiogram.utils.markdown import quote_html
import aioitertools
from faker import Faker
import more_itertools
from telethon.errors.rpcerrorlist import (UserAlreadyParticipantError, UserPrivacyRestrictedError, UserBlockedError,
                                          UserNotMutualContactError, InputUserDeactivatedError, UserKickedError,
                                          UserChannelsTooMuchError, UserDeactivatedBanError, UserBannedInChannelError,
                                          FloodWaitError, PeerFloodError, ChatWriteForbiddenError, ChannelPrivateError,
                                          ChatAdminRequiredError, ApiIdInvalidError, PhoneNumberBannedError,
                                          PhoneNumberUnoccupiedError, PhoneCodeInvalidError, PhoneCodeExpiredError)
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantsRequest
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.functions.messages import AddChatUserRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import InputPhoneContact, ChannelParticipantsRecent, TypeUser
from telethon.tl.types.auth import SentCode

from . import keyboards
from .bot import dispatcher
from .conf import Settings
from .models import Account
from .states import Menu, Scrape
from .tg import TgClient, NotAuthenticatedError
from .utils import exc_to_msg, sign_msg


logger = logging.getLogger(__name__)


def user_active(user):
    return not any([user.bot, user.deleted, user.scam, user.fake])


def user_status_valid(user, filter):
    status = user.status
    if filter:
        if not status:
            return False
        days_map = {
            'UserStatusOnline': 0, 'UserStatusRecently': 1,
            'UserStatusLastWeek': 7, 'UserStatusLastMonth': 30
        }
        name = status.to_dict()['_']
        if name == 'UserStatusOffline':
            was_online = status.was_online
            if was_online:
                days_passed = datetime.datetime.now(datetime.timezone.utc) - was_online
                days_passed = days_passed.days
            else:
                return False
        else:
            try:
                days_passed = days_map[name]
            except KeyError:
                return False
        return days_passed <= filter
    return True


async def add_to_group(client, group, user_id):
    is_channel = getattr(group, 'gigagroup', False) or getattr(group, 'megagroup', False)
    if is_channel:
        await client(InviteToChannelRequest(channel=group, users=[user_id]))
    else:
        try:
            await client(AddChatUserRequest(chat_id=group.id, user_id=user_id, fwd_limit=50))
        except UserAlreadyParticipantError:
            pass
    return True


# async def get_participants(client, group, full_user=False, filter_obj=ChannelParticipantsRecent()):
#     input_group = await client.get_input_entity(group)
#     limit = 100
#     offset = 0
#     while True:
#         result = await client(GetParticipantsRequest(input_group, filter=filter_obj, offset=offset, limit=limit, hash=0))
#         if not result.users:
#             return
#         for user in result.users:
#             if full_user:
#                 user = await client(GetFullUserRequest(user.id))
#             yield user
#         offset += len(result.users)
#         await asyncio.sleep(0.25)


async def aggressive_iter(coroutine):
    i = 1
    async for item in coroutine:
        if i % 100 == 0:
            await asyncio.sleep(0.2)
        yield item
        i += 1


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


async def add_users(client, from_id, to_id, users_added, lock):
    acc = client.account
    settings = Settings()
    last_seen_filter = settings.last_seen_filter
    from_group = await client.get_entity(from_id)
    to_group = await client.get_entity(to_id)
    async for user in aggressive_iter(client.iter_participants(from_group, aggressive=True)):
        user_id = user.id
        if user_active(user) and user_id not in users_added and user_status_valid(user, last_seen_filter):
            try:
                async with lock:
                    await add_to_group(client, to_group, user_id)
                    users_added.add(user_id)
            except (UserPrivacyRestrictedError, UserNotMutualContactError, InputUserDeactivatedError,
                    UserChannelsTooMuchError) as e:
                logger.info(str(e))
                logger.info('Skipping user.')
                continue
            except (PeerFloodError, FloodWaitError, UserDeactivatedBanError, UserBannedInChannelError,
                    UserBlockedError, UserKickedError, ChatWriteForbiddenError, ChannelPrivateError,
                    ChatAdminRequiredError) as e:
                logger.info(str(e))
                logger.info('Skipping client.')
                return
            # except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
            #     msg = exc_to_msg(e) + '\nAborting run.'
            #     await bot.send_message(chat_id, sign_msg(msg))
            #     return
            name = '{} {}'.format(user.first_name, user.last_name)
            logger.info('Added user %s', name)
            await acc.invites_incr()
            await asyncio.sleep(2)
        if not acc.can_invite:
            break
    acc.invites_reset_at = datetime.datetime.now() + datetime.timedelta(days=settings.limit_reset)
    await acc.save()


async def scrape(chat_id, queue: asyncio.Queue):
    bot = dispatcher.bot
    try:
        await main_process(chat_id, queue)
    except asyncio.CancelledError:
        await bot.send_message(chat_id, 'Run stopped.')
    await Menu.main.set()
    await bot.send_message(chat_id, 'Main', reply_markup=keyboards.main_menu())


async def scrape_repeatedly(chat_id, queue: asyncio.Queue):
    interval = 86400
    bot = dispatcher.bot
    await bot.send_message(chat_id, 'Task started. You can stop it at any moment with /stop command.')
    loading_task = None
    master = None
    clients = []
    tasks = []
    try:
        settings = Settings()
        # skip_sign_in = settings.skip_sign_in
        proxy = settings.proxy
        while True:
            users_added = set()
            if not master:
                for acc in await Account.filter(auto_created=False):
                    await acc.refresh_invites()
                    if acc.can_invite:
                        await bot.send_message(chat_id, 'Initializing account <b>{}</b>'.format(acc.safe_name))
                        master = TgClient(acc, proxy=proxy)
                        await master.connect()
                        if await master.is_user_authorized() or await sign_in(master, chat_id, queue):
                            break
                        await bot.send_message(chat_id, 'Skipping account')
                        await master.save_session()
                        await master.disconnect()
                        await asyncio.sleep(1)
                groups = {}
                async for dialog in master.iter_dialogs():
                    if dialog.is_group:
                        num_participants = dialog.entity.participants_count
                        groups[str(dialog.id)] = (dialog.title, num_participants)
                if len(groups) < 2:
                    msg = 'Main/first account should be a member of at least 2 groups (source and target).'
                    await bot.send_message(chat_id, msg)
                    break
                rows = [(key, data[0]) for key, data in groups.items()]
                queue.put_nowait(rows)
                await Scrape.select_group.set()
                reply_markup = keyboards.groups_list(rows)
                await bot.send_message(chat_id, '<b>Choose a group to add users to</b>', reply_markup=reply_markup)
                await queue.join()
                to_id = await queue.get()
                queue.task_done()
                del groups[to_id]
                to_id = int(to_id)
                rows = [(key, '{} ({})'.format(*data)) for key, data in groups.items()]
                queue.put_nowait(rows)
                await Scrape.select_multiple_groups.set()
                reply_markup = keyboards.multiple_groups(rows)
                await bot.send_message(chat_id, '<b>Select groups to scrape users from</b>', reply_markup=reply_markup)
                await queue.join()
                from_ids = [int(item) for item in await queue.get()]
                queue.task_done()
            if not master:
                await bot.send_message('No accounts available now. Stopping.')
                break
            msg = await bot.send_message(chat_id, 'Adding users')
            loading_task = asyncio.create_task(show_loading(msg))
            async for user in aggressive_iter(master.iter_participants(to_id, aggressive=True)):
                if user_active(user):
                    users_added.add(user.id)
            group_counts = {}
            for group_id in from_ids:
                count = 0
                async for user in aggressive_iter(master.iter_participants(group_id, aggressive=True)):
                    if user_active(user) and user.id not in users_added:
                        count += 1
                if count:
                    group_counts[group_id] = count
            from_ids = list(group_counts.keys())
            # TODO: Messages when no users to add or no groups selected
            await update_name(master)
            master_user = await master.get_me()
            to_group = await master.get_entity(to_id)
            lock = asyncio.Lock()
            j = 0
            for acc in await Account.filter(auto_created=True):
                if not from_ids:
                    break
                await acc.refresh_invites()
                if acc.can_invite:
                    client = TgClient(acc, proxy=proxy)
                    clients.append(client)  # to clear connection in case of cancel in the middle of code below
                    await client.connect()
                    if await client.is_user_authorized():
                        user = await client.get_me()
                        logger.error('Deleted: %s', user.deleted)
                        if not user.deleted:
                            await update_name(client)
                            phone_contact = InputPhoneContact(client_id=user.id, phone=user.phone,
                                                              first_name=user.first_name, last_name=user.last_name)
                            await master(ImportContactsRequest([phone_contact]))
                            phone_contact = InputPhoneContact(client_id=master_user.id, phone=master_user.phone,
                                                              first_name=master_user.first_name,
                                                              last_name=master_user.last_name)
                            await client(ImportContactsRequest([phone_contact]))
                            passed = False
                            while True:
                                j = j % len(from_ids)
                                try:
                                    from_id = from_ids[j]
                                except IndexError:
                                    break
                                from_group = await master.get_entity(from_id)
                                try:
                                    await add_to_group(master, from_group, user.id)
                                except (UserKickedError, UserDeactivatedBanError, UserBannedInChannelError,
                                        UserChannelsTooMuchError, InputUserDeactivatedError, UserBlockedError) as e:
                                    logger.info(str(e))
                                    logger.info('Skipping client.')
                                    break
                                except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
                                    logger.info(str(e))
                                    logger.info('Skipping group.')
                                    del from_ids[j]
                                    del group_counts[from_id]
                                    continue
                                await master.account.invites_incr()
                                try:
                                    await add_to_group(master, to_group, user.id)
                                except (UserKickedError, UserDeactivatedBanError, UserBannedInChannelError,
                                        UserChannelsTooMuchError, InputUserDeactivatedError, UserBlockedError) as e:
                                    logger.info(str(e))
                                    logger.info('Skipping client.')
                                    break
                                except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
                                    msg = exc_to_msg(e)
                                    await bot.send_message(chat_id, msg)
                                    raise asyncio.CancelledError()
                                await master.account.invites_incr()
                                count = group_counts[from_id]
                                count -= acc.invites_left
                                task = asyncio.create_task(add_users(client, from_id, to_id, users_added, lock))
                                tasks.append(task)
                                if count > 0:
                                    group_counts[from_id] = count
                                    j += 1
                                else:
                                    del from_ids[j]
                                    del group_counts[from_id]
                                passed = True
                                break
                            if passed:
                                await asyncio.sleep(10)
                            else:
                                clients.pop()
                                await client.disconnect()
                            if not master.account.can_invite:
                                master.account.invites_reset_at = datetime.datetime.now() + datetime.timedelta(seconds=interval)
                                await master.account.save()
                                break
                            continue
                    logger.error('Deleting account {}'.format(acc.name))
                    await acc.delete()
                    await client.disconnect()
            await asyncio.gather(tasks)
            for client in clients:
                await client.save_session()
                await client.disconnect()
            tasks = []
            loading_task.cancel()
            await loading_task
            await bot.send_message(chat_id, 'Users added.')
            wait_until = datetime.datetime.now() + datetime.timedelta(seconds=interval)
            msg = 'Next scrape will start at {}.'.format(wait_until.strftime('%d-%m-%Y %H:%M'))
            await bot.send_message(chat_id, msg)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        if loading_task and not loading_task.done():
            loading_task.cancel()
            await loading_task
        for task in tasks:
            if not task.done():
                task.cancel()
        for client in clients:
            await client.save_session()
            await client.disconnect()
        await asyncio.gather(tasks)
        await bot.send_message(chat_id, 'Run stopped.')
    if master:
        await master.save_session()
        await master.disconnect()
    await Menu.main.set()
    await bot.send_message(chat_id, 'Main', reply_markup=keyboards.main_menu())

# async def scrape_repeatedlyy(chat_id, queue: asyncio.Queue):
#     interval = 86400
#     bot = dispatcher.bot
#     await bot.send_message(chat_id, 'Task started. You can stop it at any moment with /stop command.')
#     while True:
#         settings = Settings()
#         skip_sign_in = settings.skip_sign_in
#         proxy = settings.proxy
#         users_added = set()
#         accounts = list(await Account.all())
#         for i, master_acc in enumerate(accounts):
#             await master_acc.refresh_invites()
#             if master_acc.can_invite:
#                 await asyncio.sleep(1)
#                 await bot.send_message(chat_id, 'Initializing account <b>{}</b>'.format(master_acc.safe_name))
#                 async with TgClient(master_acc) as master:
#                     if not await master.is_user_authorized():
#                         if master_acc.auto_created and skip_sign_in:
#                             await bot.send_message(chat_id, 'Skipping and deleting not signed in account')
#                             await master_acc.delete()
#                             continue
#                         elif not await sign_in(master, chat_id, queue):
#                             await bot.send_message(chat_id, 'Skipping account')
#                             continue
#                     await update_name(master)
#                     master_user = await master.get_me()
#                     groups = {}
#                     async for dialog in master.iter_dialogs():
#                         if dialog.is_group:
#                             num_participants = dialog.entity.participants_count
#                             groups[str(dialog.id)] = (dialog.title, num_participants)
#                     if len(groups) < 2:
#                         msg = 'Main/first account should be a member of at least 2 groups (source and target).'
#                         await bot.send_message(chat_id, msg)
#                         return
#                     rows = [(key, data[0]) for key, data in groups.items()]
#                     queue.put_nowait(rows)
#                     await Scrape.select_group.set()
#                     reply_markup = keyboards.groups_list(rows)
#                     await bot.send_message(chat_id, '<b>Choose a group to add users to</b>', reply_markup=reply_markup)
#                     await queue.join()
#                     to_id = await queue.get()
#                     queue.task_done()
#                     del groups[to_id]
#                     to_id = int(to_id)
#                     rows = [(key, '{} ({})'.format(*data)) for key, data in groups.items()]
#                     queue.put_nowait(rows)
#                     await Scrape.select_multiple_groups.set()
#                     reply_markup = keyboards.multiple_groups(rows)
#                     await bot.send_message(chat_id, '<b>Select groups to scrape users from</b>', reply_markup=reply_markup)
#                     await queue.join()
#                     from_ids = [int(item) for item in await queue.get()]
#                     queue.task_done()
#                     # TODO: loading
#                     msg = await bot.send_message(chat_id, 'Preparing data')
#                     loading_task = asyncio.create_task(show_loading(msg), name=str(chat_id))
#                     async for user in aggressive_iter(master.iter_participants(to_id, aggressive=True)):
#                         if user_active(user):
#                             users_added.add(user.id)
#                     group_counts = []
#                     for group_id in from_ids:
#                         count = 0
#                         async for user in aggressive_iter(master.iter_participants(group_id, aggressive=True)):
#                             if user_active(user) and user.id not in users_added:
#                                 count += 1
#                         group_counts.append((group_id, count))
#                     groups_map = {}
#                     accounts = accounts[i + 1:]
#                     i = 0
#                     j = 0
#                     while master_acc.can_invite:
#                         try:
#                             acc = accounts[i]
#                         except IndexError:
#                             break
#                         await acc.refresh_invites()
#                         if acc.can_invite:
#                             await asyncio.sleep(1)
#                             await bot.send_message(chat_id, 'Initializing account <b>{}</b>'.format(acc.safe_name))
#                             async with TgClient(acc) as client:
#                                 if not await client.is_user_authorized():
#                                     if acc.auto_created and skip_sign_in:
#                                         await bot.send_message(chat_id, 'Skipping and deleting not signed in account')
#                                         await acc.delete()
#                                         i += 1
#                                         continue
#                                     elif not await sign_in(client, chat_id, queue):
#                                         await bot.send_message(chat_id, 'Skipping account')
#                                         i += 1
#                                         continue
#                                 await update_name(client)
#                                 user = await client.get_me()
#                                 # TODO: Delay for same group
#                                 j = j % len(group_counts)
#                                 try:
#                                     from_id, count = group_counts[j]
#                                 except IndexError:
#                                     break
#                                 phone_contact = InputPhoneContact(client_id=user.id, phone=user.phone,
#                                                                   first_name=user.first_name, last_name=user.last_name)
#                                 await master(ImportContactsRequest([phone_contact]))
#                                 phone_contact = InputPhoneContact(client_id=master_user.id, phone=master_user.phone,
#                                                                   first_name=master_user.first_name,
#                                                                   last_name=master_user.last_name)
#                                 await client(ImportContactsRequest([phone_contact]))
#                                 from_group = await master.get_entity(from_id)
#                                 await master_acc.invites_incr()
#                                 try:
#                                     await add_to_group(master, from_group, user.id)
#                                 except (UserKickedError, UserDeactivatedBanError, UserBannedInChannelError,
#                                         UserChannelsTooMuchError, InputUserDeactivatedError, UserBlockedError) as e:
#                                     logger.info(str(e))
#                                     logger.info('Skipping client.')
#                                     i += 1
#                                     continue
#                                 except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
#                                     logger.info(str(e))
#                                     logger.info('Skipping group.')
#                                     del group_counts[j]
#                                     continue
#                                 to_group = await master.get_entity(to_id)
#                                 await master_acc.invites_incr()
#                                 try:
#                                     await add_to_group(master, to_group, user.id)
#                                 except (UserKickedError, UserDeactivatedBanError, UserBannedInChannelError,
#                                         UserChannelsTooMuchError, InputUserDeactivatedError, UserBlockedError) as e:
#                                     logger.info(str(e))
#                                     logger.info('Skipping client.')
#                                     i += 1
#                                     continue
#                                 except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
#                                     msg = exc_to_msg(e) + '\nAborting run.'
#                                     await bot.send_message(chat_id, msg)
#                                     return
#                                 groups_map[acc.id] = from_id
#                                 count -= acc.invites_left
#                                 if count:
#                                     group_counts[j] = (from_id, count)
#                                     j += 1
#                                 else:
#                                     del group_counts[j]
#                                 i += 1
#                 master_acc.invites_reset_at = datetime.datetime.now() + datetime.timedelta(seconds=interval)
#                 await master_acc.save()
#                 loading_task.cancel()
#                 break
#
#         if not groups_map:
#             await bot.send_message(chat_id, 'No accounts were added to groups.')
#         else:
#             msg = await bot.send_message(chat_id, 'Adding users')
#             loading_task = asyncio.create_task(show_loading(msg), name=str(chat_id))
#             lock = asyncio.Lock()
#             accounts = await Account.filter(id__in=groups_map.keys())
#             async with AsyncExitStack() as stack:
#                 tasks = []
#                 for acc in accounts:
#                     client = await stack.enter_async_context(TgClient(acc))
#                     from_id = groups_map[acc.id]
#                     task = asyncio.create_task(add_users(client, from_id, to_id, users_added, lock))
#                     tasks.append(task)
#                 await asyncio.gather(*tasks)
#             loading_task.cancel()
#             await bot.send_message(chat_id, 'Users added.')
#         wait_until = datetime.datetime.now() + datetime.timedelta(seconds=interval)
#         msg = 'Next scrape will start at {}.'.format(wait_until.strftime('%d-%m-%Y %H:%M'))
#         await bot.send_message(chat_id, msg)
#         await asyncio.sleep(interval)



# async def scrape_repeatedly(chat_id, bot: Bot, queue, interval=86400, *args, **kwargs):
#     accounts = await init_accounts(chat_id, bot, queue)
#     if not accounts:
#         msg = '<i><b>No accounts were logged in. Run aborted.</b></i>'
#         await bot.send_message(chat_id, sign_msg(msg))
#     else:
#         while True:
#             try:
#                 accounts = await main_process(chat_id, bot, queue, accounts)
#             except asyncio.CancelledError:
#                 msg = '<i><b>Run stopped.</b></i>'
#                 await bot.send_message(chat_id, sign_msg(msg))
#             else:
#                 if accounts:
#                     now = datetime.datetime.now().strftime('%m %b, %y %H:%S')
#                     msg = '<i><b>Run completed. Next run will be at {}.</b></i>'.format(now)
#                     await bot.send_message(chat_id, sign_msg(msg), reply_markup=Keyboard.run_control)
#                     await asyncio.sleep(interval)
#                     continue
#             break
#     await Main.main.set()
#     await bot.send_message(chat_id, 'Main', reply_markup=Keyboard.main_menu)

async def show_loading(message):
    text = message.text
    symbols = '❤💔💙🔥'
    async for sym in aioitertools.cycle(symbols):
        msg = '{} {}'.format(text, sym)
        message = await message.edit_text(msg)
        await asyncio.sleep(0.5)
