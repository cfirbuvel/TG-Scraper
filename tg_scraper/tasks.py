import asyncio
from contextlib import AsyncExitStack
import datetime
import logging
from collections import OrderedDict
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


async def get_participants(client, group, full_user=False, filter_obj=ChannelParticipantsRecent()):
    input_group = await client.get_input_entity(group)
    limit = 100
    offset = 0
    while True:
        result = await client(GetParticipantsRequest(input_group, filter=filter_obj, offset=offset, limit=limit, hash=0))
        if not result.users:
            return
        for user in result.users:
            if full_user:
                user = await client(GetFullUserRequest(user.id))
            yield user
        offset += len(result.users)
        await asyncio.sleep(0.25)


def get_user_name(user, fallback='Guest'):
    first_name = user.first_name or fallback
    last_name = user.last_name or fallback
    return first_name, last_name


async def update_name(client):
    fake = Faker()
    first_name = fake.first_name()
    last_name = fake.last_name()
    await client(UpdateProfileRequest(first_name=first_name, last_name=last_name))


async def sign_in(client, chat_id, queue):
    # if await client.is_user_authorized():
    #     await update_name(client)
    #     return await client.get_me()
    # if not skip_sign_in:
    bot = dispatcher.bot
    acc = client.account
    await bot.send_message(chat_id, 'Signing in <b>{}</b>'.format(acc.safe_name))
    code = None
    while True:
        try:
            if code:
                await client.sign_in(acc.phone, code)
                # await update_name(client)
                return True
            else:
                await client.send_code_request(acc.phone)
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


async def main_process(chat_id, queue):
    bot = dispatcher.bot
    await bot.send_message(chat_id, 'Task started. You can stop it at any moment with /stop command.')
    settings = Settings()
    skip_sign_in = settings.skip_sign_in
    accounts = []
    # TODO: Show progress for initializing accounts
    await bot.send_message(chat_id, 'Initializing accounts.')
    for acc in await Account.all():
        await acc.refresh_invites()
        if acc.can_invite:
            async with TgClient(acc) as client:
                if not await client.is_user_authorized():
                    if (acc.auto_created and skip_sign_in) or not await sign_in(client, chat_id, queue):
                        continue
                await update_name(client)
            accounts.append(acc)
    if len(accounts) < 2:
        await bot.send_message('No accounts ready. Stopping.')
        return
    invites_total = sum(acc.invites_left for acc in accounts)
    msg = 'Average number of invites can be sent in next {} days: {}'.format(settings.limit_reset, invites_total)
    await bot.send_message(chat_id, msg)
    # all_accounts = more_itertools.seekable(await Account.all())
    master_acc = accounts[0]
    added_participants = set()
    async with TgClient(master_acc) as client:
        groups = OrderedDict()
        async for dialog in client.iter_dialogs():
            if dialog.is_group:
                groups[str(dialog.id)] = dialog.title
        if len(groups) < 2:
            await bot.send_message('Main/first account should be a member of at least 2 groups (source and target).')
            return
        queue.put_nowait(groups)
        await Scrape.group_from.set()
        reply_markup = keyboards.groups_list(list(groups.items()))
        await bot.send_message(chat_id, '<b>Choose a group to scrape users from</b>', reply_markup=reply_markup)
        await queue.join()
        from_id, to_id = await queue.get()
        queue.task_done()
        from_id = int(from_id)
        to_id = int(to_id)
        i = 1
        async for user in client.iter_participants(to_id, aggressive=True):
            i += 1
            if user_active(user):
                added_participants.add(user.id)
            if i % 5000 == 0:
                await asyncio.sleep(10)
    # loading_task =
    await bot.send_message(chat_id, '<i><b>Running main actions</b></i>')
    join_delay = settings.join_delay
    last_seen_filter = settings.last_seen_filter
    prev_acc = master_acc
    for acc in accounts[1:]:
        async with TgClient(acc) as client:
            user = await client.get_me()
            async with TgClient(prev_acc) as prev_client:
                prev_user = await prev_client.get_me()
                phone_contact = InputPhoneContact(client_id=user.id, phone=user.phone,
                                                  first_name=user.first_name, last_name=user.last_name)
                await prev_client(ImportContactsRequest([phone_contact]))
                phone_contact = InputPhoneContact(client_id=prev_user.id, phone=prev_user.phone,
                                                  first_name=prev_user.first_name, last_name=prev_user.last_name)
                await client(ImportContactsRequest([phone_contact]))
                from_group = await prev_client.get_entity(from_id)
                to_group = await prev_client.get_entity(to_id)
                try:
                    await add_to_group(prev_client, from_group, user.id)
                    await add_to_group(prev_client, to_group, user.id)
                    await prev_acc.invites_incr(num=2)
                except (UserKickedError, UserDeactivatedBanError, UserBannedInChannelError,
                        UserChannelsTooMuchError, InputUserDeactivatedError, UserBlockedError) as e:
                    logger.info(str(e))
                    logger.info('Skipping client.')
                    continue
                except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
                    msg = exc_to_msg(e) + '\nAborting run.'
                    await bot.send_message(chat_id, msg)
                    return
            prev_acc = acc
            from_group = await client.get_entity(from_id)
            to_group = await client.get_entity(to_id)
            i = 0
            async for user in client.iter_participants(from_group, aggressive=True):
                if acc.invites_left <= 2:
                    break
                i += 1
                if i % 5000 == 0:
                    await asyncio.sleep(10)
                user_id = user.id
                if user_active(user) and user_id not in added_participants and user_status_valid(user, last_seen_filter):
                    name = '{} {}'.format(user.first_name, user.last_name)
                    try:
                        await add_to_group(client, to_group, user_id)
                    except (UserPrivacyRestrictedError, UserNotMutualContactError, InputUserDeactivatedError,
                            UserChannelsTooMuchError, UserBlockedError, UserKickedError,
                            UserBannedInChannelError,) as e:
                        logger.info(str(e))
                        logger.info('Skipping user.')
                        continue
                    except (PeerFloodError, FloodWaitError, UserDeactivatedBanError) as e:
                        logger.info(str(e))
                        logger.info('Skipping client.')
                        prev_acc = master_acc
                        break
                    except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
                        msg = exc_to_msg(e) + '\nAborting run.'
                        await bot.send_message(chat_id, sign_msg(msg))
                        return
                    logger.info('Added user %s', name)
                    added_participants.add(user_id)
                    await acc.invites_incr()
                    await asyncio.sleep(2)
            else:
                await bot.send_message('All users from specified group were processed.')
                return
        await asyncio.sleep(join_delay)
    return accounts


async def scrape(chat_id, queue: asyncio.Queue):
    bot = dispatcher.bot
    try:
        await main_process(chat_id, queue)
    except asyncio.CancelledError:
        await bot.send_message(chat_id, 'Run stopped.')
    await Menu.main.set()
    await bot.send_message(chat_id, 'Menu', reply_markup=keyboards.main_menu())


async def scrape_repeatedly(chat_id, bot: Bot, queue, interval=86400, *args, **kwargs):
    accounts = await init_accounts(chat_id, bot, queue)
    if not accounts:
        msg = '<i><b>No accounts were logged in. Run aborted.</b></i>'
        await bot.send_message(chat_id, sign_msg(msg))
    else:
        while True:
            try:
                accounts = await main_process(chat_id, bot, queue, accounts)
            except asyncio.CancelledError:
                msg = '<i><b>Run stopped.</b></i>'
                await bot.send_message(chat_id, sign_msg(msg))
            else:
                if accounts:
                    now = datetime.datetime.now().strftime('%m %b, %y %H:%S')
                    msg = '<i><b>Run completed. Next run will be at {}.</b></i>'.format(now)
                    await bot.send_message(chat_id, sign_msg(msg), reply_markup=Keyboard.run_control)
                    await asyncio.sleep(interval)
                    continue
            break
    await Menu.main.set()
    await bot.send_message(chat_id, 'Menu', reply_markup=Keyboard.main_menu)


async def show_loading(message):
    text = message.text
    symbols = '❤💔💙🔥'
    async for sym in aioitertools.cycle(symbols):
        msg = '{} {}'.format(text, sym)
        message = await message.edit_text(msg)
        await asyncio.sleep(0.5)
