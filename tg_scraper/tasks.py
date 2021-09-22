import asyncio
import datetime
import logging
from collections import OrderedDict
import time

from aiogram.bot.bot import Bot
from aiogram.utils.markdown import html_decoration as md
from more_itertools import always_iterable
from telethon.errors.rpcerrorlist import (UserAlreadyParticipantError, UserPrivacyRestrictedError, UserBlockedError,
                                          UserNotMutualContactError, InputUserDeactivatedError, UserKickedError,
                                          UserChannelsTooMuchError, UserDeactivatedBanError, UserBannedInChannelError,
                                          FloodWaitError, PeerFloodError, ChatWriteForbiddenError, ChannelPrivateError,
                                          ChatAdminRequiredError, ApiIdInvalidError, PhoneNumberBannedError,
                                          PhoneCodeInvalidError, PhoneCodeExpiredError)
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantsRequest
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.functions.messages import AddChatUserRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import InputPhoneContact, ChannelParticipantsRecent, User
from telethon.tl.types.auth import SentCode

from tg_scraper import Answer
from tg_scraper.inline_keyboards import InlineKeyboard as Keyboard
from tg_scraper.models import Account
from tg_scraper.states import MenuState, AddAccountState, ScrapeState
from tg_scraper.pieces import main_menu
from tg_scraper.utils import TgClient, tg_error_msg, sign_msg


logger = logging.getLogger(__name__)


def user_valid(user):
    return not any([user.bot, user.deleted, user.scam, user.fake])


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


# async def add_participants(client, from_group, to_group, already_added):
#     count = 0
#     # TODO: Floodwait
#     async for user in get_participants(client, from_group.id):
#         user_id = user.id
#         if user_valid(user) and user_id not in already_added:
#             name = '{} {}'.format(user.first_name, user.last_name)
#             # input_user = await client.get_input_entity(user_id)
#             try:
#                 await add_to_group(client, to_group, user_id)
#                 # added = await add_to_group(client, input_to, is_channel, input_user)
#             except (UserPrivacyRestrictedError, tg_errors.UserNotMutualContactError,
#                     tg_errors.InputUserDeactivatedError, tg_errors.UserChannelsTooMuchError,
#                     tg_errors.UserBlockedError, tg_errors.UserKickedError,
#                     tg_errors.UserDeactivatedBanError, tg_errors.UserBannedInChannelError,) as ex:
#                 logger.warning('Skipping user: %s', str(ex))
#                 continue
#             except (tg_errors.PeerFloodError, tg_errors.FloodWaitError,) as ex:
#                 logger.warning('Skipping client: %s', str(ex))
#                 break
#             except (tg_errors.ChatWriteForbiddenError, tg_errors.ChannelPrivateError,
#                     tg_errors.ChatAdminRequiredError) as ex:
#                 # TODO: Stop script here
#                 logger.warning('Channel restricted: %s', str(ex))
#                 break
#             logger.info('Added user %s', name)
#             already_added.add(user_id)
#             count += 1
#             await asyncio.sleep(3)
#             if count >= 50:
#                 break
#     return already_added


async def init_accounts(chat_id, bot, queue):
    result = []
    for acc in await Account.all():
        async with TgClient(acc) as client:
            msg = '<i>Initializing account: <b>{}</b>.</i>'.format(md.quote(str(acc)))
            await bot.send_message(chat_id, sign_msg(msg))
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
                    await ScrapeState.ENTER_CODE.set()
                    await bot.send_message(chat_id, sign_msg(msg), reply_markup=Keyboard.enter_code)
                    answer = await queue.get()
                    queue.task_done()
                    if answer == Answer.SKIP:
                        break
                    elif answer == Answer.CODE:
                        code = await queue.get()
                        queue.task_done()
            if user:
                result.append(acc)
    return result


async def main_process(chat_id, bot, queue, accounts):
    root_acc = accounts[0]
    async with TgClient(root_acc) as root_client:
        groups = {}
        group_names = OrderedDict()
        async for dialog in root_client.iter_dialogs():
            if dialog.is_group:
                group_id = str(dialog.id)
                groups[group_id] = dialog
                group_names[group_id] = dialog.title
        queue.put_nowait(group_names)
        await ScrapeState.GROUP_FROM.set()
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
        counter = 0
        async for user in root_client.iter_participants(to_group, filter=ChannelParticipantsRecent()):
            counter += 1
            if user_valid(user):
                added_participants.add(user.id)
        delay = 3
        for acc in accounts[1:]:
            async with TgClient(acc) as client:
                user = await client.get_me()
                phone_contact = InputPhoneContact(client_id=user.id, phone=acc.phone,
                                                  first_name=acc.name, last_name=acc.name)
                await root_client(ImportContactsRequest(contacts=[phone_contact]))
                # phone_contact = InputPhoneContact(client_id=main_user.id, phone=main_acc.phone,
                #                                   first_name=main_acc.name, last_name=main_acc.name)
                # await client(ImportContactsRequest([phone_contact]))
                # input_user = await main_client.get_input_entity(user.id)

                # msg = '<i>Adding <b>{}</b> account to source and target groups.</i>'.format(md.quote(str(acc)))
                # await bot.send_message(chat_id, sign_msg(msg))
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
                async for user in client.iter_participants(from_group_entity, filter=ChannelParticipantsRecent()):
                    user_id = user.id
                    if user_valid(user) and user_id not in added_participants:
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
                        await asyncio.sleep(delay)
                        if count >= 50:
                            break
                await asyncio.sleep(delay)
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
    await MenuState.MAIN.set()
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
    await MenuState.MAIN.set()
    await bot.send_message(chat_id, 'Menu', reply_markup=Keyboard.main_menu)
