import asyncio
import datetime
import logging
from collections import OrderedDict
import random

from aiogram.bot.bot import Bot
from aiogram.utils.markdown import html_decoration as md
from faker import Faker
from telethon.errors.rpcerrorlist import (UserAlreadyParticipantError, UserPrivacyRestrictedError, UserBlockedError,
                                          UserNotMutualContactError, InputUserDeactivatedError, UserKickedError,
                                          UserChannelsTooMuchError, UserDeactivatedBanError, UserBannedInChannelError,
                                          FloodWaitError, PeerFloodError, ChatWriteForbiddenError, ChannelPrivateError,
                                          ChatAdminRequiredError, ApiIdInvalidError, PhoneNumberBannedError,
                                          PhoneCodeInvalidError, PhoneCodeExpiredError)
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantsRequest
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.functions.messages import AddChatUserRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import InputPhoneContact, ChannelParticipantsRecent, User
from telethon.tl.types.auth import SentCode

from tg_scraper import Answer
from tg_scraper.inline_keyboards import InlineKeyboard as Keyboard
from tg_scraper.models import Account, Settings
from tg_scraper.states import MenuState, AddAccountState, ScrapeState
from tg_scraper.utils import TgClient, tg_error_msg, sign_msg


logger = logging.getLogger(__name__)


def user_active(user):
    return not any([user.bot, user.deleted, user.scam, user.fake])


def user_status_valid(user, filter_value=0):
    status = user.status
    if filter_value:
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
        return days_passed <= filter_value
    return True


async def add_to_group(client, group, user_id):
    if group.is_channel:
        await client(InviteToChannelRequest(channel=group.id, users=[user_id]))
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


async def init_accounts(chat_id, bot, queue):
    result = []
    fake = Faker()
    for acc in await Account.all():
        async with TgClient(acc) as client:
            msg = '<i>Initializing account: <b>{}</b>.</i>'.format(md.quote(str(acc)))
            await bot.send_message(chat_id, sign_msg(msg))
            user = None
            if await client.is_user_authorized():
                user = await client.get_me()
            else:
                code = None
                phone_code_hash = None
                while True:
                    try:
                        res = await client.sign_in(acc.phone, code, phone_code_hash=phone_code_hash)
                        if type(res) == SentCode:
                            phone_code_hash = res.phone_code_hash
                            msg = ('Enter the code for: <b>{}</b>\n'
                                   'Please divide it with whitespaces, like: <b>41 9 78</b>').format(md.quote(str(acc)))
                    except (ApiIdInvalidError, PhoneNumberBannedError, FloodWaitError) as ex:
                        msg = '<i>{}</i>'.format(md.quote(tg_error_msg(ex)))
                        if type(ex) in (ApiIdInvalidError, PhoneNumberBannedError):
                            msg += '\n<i>Deleted account.</i>'
                            await acc.delete()
                        await bot.send_message(chat_id, sign_msg(msg), disable_web_page_preview=True)
                        break
                    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as ex:
                        msg = '<i><b>{}</b></i>'.format(md.quote(tg_error_msg(ex)))
                    if type(res) == User:
                        user = res
                        break
                    await ScrapeState.enter_code.set()
                    await bot.send_message(chat_id, sign_msg(msg), reply_markup=Keyboard.enter_code)
                    answer = await queue.get()
                    queue.task_done()
                    if answer == Answer.SKIP:
                        break
                    elif answer == Answer.CODE:
                        code = await queue.get()
                        queue.task_done()
                    else:
                        code = None
                    print('Resending')

            if user:
                first_name = fake.first_name()
                last_name = fake.last_name()
                await client(UpdateProfileRequest(first_name=first_name, last_name=last_name))
                result.append(acc)
    return result


async def main_process(chat_id, bot, queue, accounts):
    settings = await Settings.get()
    root_acc = accounts[0]
    async with TgClient(root_acc) as root_client:
        root_user = await root_client.get_me()
        groups = {}
        group_names = OrderedDict()
        async for dialog in root_client.iter_dialogs():
            if dialog.is_group:
                group_id = str(dialog.id)
                groups[group_id] = dialog
                group_names[group_id] = dialog.title
        queue.put_nowait(group_names)
        await ScrapeState.group_from.set()
        msg = '<b>Choose a group to scrape users from</b>'
        await bot.send_message(chat_id, sign_msg(msg), reply_markup=Keyboard.groups(group_names))
        await queue.join()
        from_id, to_id = await queue.get()
        queue.task_done()
        from_group = groups[from_id]
        to_group = groups[to_id]
        msg = '<i><b>Running main actions.</b></i>'
        await bot.send_message(chat_id, sign_msg(msg), reply_markup=Keyboard.run_control)
        added_participants = set()
        counter = 1
        async for user in root_client.iter_participants(to_group, aggressive=True):
            counter += 1
            if user_active(user):
                added_participants.add(user.id)
            if counter % 10000 == 0:
                await asyncio.sleep(5)
        status_filter = settings.status_filter
        join_delay = settings.join_delay
        for acc in accounts[1:]:
            async with TgClient(acc) as client:
                user = await client.get_me()
                first_name, last_name = get_user_name(user, acc.name)
                phone_contact = InputPhoneContact(client_id=user.id, phone=acc.phone,
                                                  first_name=first_name, last_name=last_name)
                await root_client(ImportContactsRequest([phone_contact]))
                first_name, last_name = get_user_name(root_user, root_acc.name)
                phone_contact = InputPhoneContact(client_id=root_user.id, phone=root_user.phone,
                                                  first_name=first_name, last_name=last_name)
                await client(ImportContactsRequest([phone_contact]))
                # input_user = await main_client.get_input_entity(user.id)

                # msg = '<i>Adding <b>{}</b> account to source and target groups.</i>'.format(md.quote(str(acc)))
                # await bot.send_message(chat_id, sign_msg(msg))
                await asyncio.sleep(join_delay + random.randint(-10, 10))
                try:
                    await add_to_group(root_client, from_group, user.id)
                    await add_to_group(root_client, to_group, user.id)
                except (UserKickedError, UserDeactivatedBanError, UserBannedInChannelError,
                        UserChannelsTooMuchError, InputUserDeactivatedError, UserBlockedError) as ex:
                    # msg = tg_error_msg(ex) + '\nSkipping.'
                    # await bot.send_message(chat_id, msg)
                    logger.info(str(ex))
                    logger.info('Skipping client.')
                    continue
                except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as ex:
                    msg = tg_error_msg(ex) + '\nAborting run.'
                    await bot.send_message(chat_id, sign_msg(msg))
                    return
                count = 0
                # async for user in get_participants(client, from_group):
                from_group_entity = await client.get_entity(from_group.id)
                users_counter = 0
                async for user in client.iter_participants(from_group_entity, aggressive=True):
                    users_counter += 1
                    if users_counter % 10000 == 0:
                        await asyncio.sleep(5)
                    user_id = user.id
                    if user_active(user) and user_id not in added_participants and user_status_valid(user, status_filter):
                        name = '{} {}'.format(user.first_name, user.last_name)
                        # input_user = await client.get_input_entity(user_id)
                        try:
                            await add_to_group(client, to_group, user_id)
                        except (UserPrivacyRestrictedError, UserNotMutualContactError, InputUserDeactivatedError,
                                UserChannelsTooMuchError, UserBlockedError, UserKickedError, UserBannedInChannelError,) as ex:
                            # msg = tg_error_msg(ex) + '\nSkipping user.'
                            # await bot.send_message(chat_id, sign_msg(msg))
                            logger.info(str(ex))
                            logger.info('Skipping user.')
                            continue
                        except (PeerFloodError, FloodWaitError, UserDeactivatedBanError) as ex:
                            # msg = tg_error_msg(ex) + '\nSkipping client.'
                            # await bot.send_message(chat_id, sign_msg(msg))
                            logger.info(str(ex))
                            logger.info('Skipping client.')
                            break
                        except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as ex:
                            msg = tg_error_msg(ex) + '\nAborting run.'
                            await bot.send_message(chat_id, sign_msg(msg))
                            return
                        logger.info('Added user %s', name)
                        added_participants.add(user_id)
                        count += 1
                        await asyncio.sleep(2)
                        if count >= 50:
                            break
    return accounts


async def scrape_task(chat_id, bot: Bot, queue: asyncio.Queue):
    try:
        accounts = await init_accounts(chat_id, bot, queue)
        if not accounts:
            msg = '<i><b>No accounts were logged in. Run aborted.</b></i>'
        else:
            await main_process(chat_id, bot, queue, accounts)
            msg = '<i><b>Run completed.</b></i>'
    except asyncio.CancelledError:
        msg = '<i><b>Run stopped.</b></i>'
    await bot.send_message(chat_id, sign_msg(msg))
    await MenuState.main.set()
    await bot.send_message(chat_id, 'Menu', reply_markup=Keyboard.main_menu)


async def scrape_task_repeated(chat_id, bot: Bot, queue, interval=86400, *args, **kwargs):
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
    await MenuState.main.set()
    await bot.send_message(chat_id, 'Menu', reply_markup=Keyboard.main_menu)
