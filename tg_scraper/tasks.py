import asyncio
import logging
from collections import OrderedDict
from pprint import pprint

from aiogram.bot.bot import Bot
from aiogram.dispatcher.storage import FSMContext
from aiogram.types.message import ParseMode
from aiogram.utils.markdown import escape_md
from more_itertools import always_iterable
from telethon import TelegramClient
from telethon.errors import rpcerrorlist as tg_errors
from telethon.tl.functions.channels import InviteToChannelRequest, JoinChannelRequest
from telethon.tl.functions.contacts import AddContactRequest, AcceptContactRequest, ImportContactsRequest
from telethon.tl.functions.messages import AddChatUserRequest, CheckChatInviteRequest, ImportChatInviteRequest
from telethon.tl.types import InputPhoneContact, Chat, Channel

from tg_scraper.models import Account
from tg_scraper.inline_keyboards import MainMenuKeyboard, EnterCodeKeyboard, ScrapeKeyboard, GroupsKeyboard
from tg_scraper.states import MenuState, AccountState, ScrapeState, SelectGroupState
from tg_scraper.pieces import main_menu
from tg_scraper.utils import TgClient, wait_for_state_value


logger = logging.getLogger(__name__)


async def add_to_group(client, group, input_user):
    if group.is_channel:
        await client(InviteToChannelRequest(channel=group.input_entity, users=[input_user]))
    else:
        try:
            await client(AddChatUserRequest(chat_id=group.id, user_id=input_user, fwd_limit=50))
        except tg_errors.UserAlreadyParticipantError:
            pass


async def add_participants(client, group_from, group_to, already_added):
    # added_participants = []
    count = 0
    input_group = await client.get_input_entity(group_to)
    is_channel = getattr(group_to, 'gigagroup', None) or getattr(group_to, 'megagroup', None)
    async for user in client.iter_participants(group_from, aggressive=True):
        # user.access_hash
        user_id = user.id
        if not user.bot and user_id not in already_added:
            name = '{} {}'.format(user.first_name, user.last_name)
            input_user = await client.get_input_entity(user_id)
            try:
                if is_channel:
                    await client(InviteToChannelRequest(channel=input_group, users=[input_user]))
                else:
                    await client(AddChatUserRequest(chat_id=input_group, user_id=input_user, fwd_limit=50))
            except (tg_errors.UserPrivacyRestrictedError, tg_errors.UserNotMutualContactError,
                    tg_errors.InputUserDeactivatedError, tg_errors.UserChannelsTooMuchError,
                    tg_errors.UserBlockedError, tg_errors.UserKickedError,
                    tg_errors.UserDeactivatedBanError, tg_errors.UserBannedInChannelError,) as e:
                logger.warning('Skipping user: %s', str(e))
                continue
            except (tg_errors.PeerFloodError, tg_errors.FloodWaitError,) as e:
                logger.warning('Skipping client: %s', str(e))
                break
            except (tg_errors.ChatWriteForbiddenError, tg_errors.ChannelPrivateError,
                    tg_errors.ChatAdminRequiredError) as e:
                # TODO: Stop script here
                logger.warning('Channel restricted: %s', str(e))
                break
            logger.info('Added user %s', name)
            already_added.add(user_id)
            count += 1
            await asyncio.sleep(3)
            if count >= 50:
                break
    return already_added


async def run_scrape(bot: Bot, chat_id, state: FSMContext):
    accounts = []
    for acc in await Account.all():
        async with TgClient(acc) as client:
            msg = r'_Initializing account: *{}*\._'.format(escape_md(str(acc)))
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN_V2)
            signed_in = await client.is_user_authorized()
            logger.info('Acc signed in: %s', signed_in)
            if not signed_in:
                while True:
                    try:
                        phone_hash = (await client.send_code_request(acc.phone)).phone_code_hash
                    except tg_errors.ApiIdInvalidError:
                        await acc.set_invalid_details()
                        await bot.send_message(chat_id=chat_id, text=r'_API id or hash is not valid\._',
                                               parse_mode=ParseMode.MARKDOWN_V2)
                    except tg_errors.PhoneNumberBannedError:
                        await acc.set_phone_banned()
                        await bot.send_message(chat_id=chat_id, text=r'_Phone number is banned and cannot be used anymore\._',
                                               parse_mode=ParseMode.MARKDOWN_V2)
                    except tg_errors.FloodWaitError as e:
                        await acc.set_flood_wait(e.seconds)
                        msg = r'_Account was banned for *{}* seconds \(caused by code request\)\._'.format(e.seconds)
                        await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN_V2)
                    else:
                        await AccountState.ENTER_CODE.set()
                        msg = ('Enter the code for *{}*\n'
                               'Please divide it with whitespaces, for example: *41 9 78*').format(escape_md(str(acc)))
                        await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN_V2,
                                               reply_markup=EnterCodeKeyboard())
                        answer = await wait_for_state_value(state, 'answer')
                        if answer == 'code':
                            code = (await state.get_data())['login_code']
                            try:
                                await client.sign_in(acc.phone, code, phone_code_hash=phone_hash)
                            except (tg_errors.PhoneCodeInvalidError, tg_errors.PhoneCodeExpiredError) as e:
                                if type(e) == tg_errors.PhoneCodeInvalidError:
                                    msg = 'Code is not valid'
                                else:
                                    msg = 'Code has expired'
                                await AccountState.ENTER_CODE.set()
                                await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN_V2,
                                                       reply_markup=EnterCodeKeyboard())
                                answer = await wait_for_state_value(state, 'answer')
                            else:
                                signed_in = True
                        await state.reset_data()
                        if answer == 'resend':
                            continue
                    break
        if signed_in:
            accounts.append(acc.id)
    if not accounts:
        await bot.send_message(chat_id=chat_id, text=r'_No accounts were logged in. Aborting run\._',
                               parse_mode=ParseMode.MARKDOWN_V2)
        await ScrapeState.MAIN.set()
        await bot.send_message(chat_id=chat_id, text='Select mode', reply_markup=ScrapeKeyboard())
        return
    accounts = await Account.filter(id__in=accounts)
    main_acc = accounts[0]
    async with TgClient(main_acc) as main_client:
        groups_map = {}
        groups = OrderedDict()
        count = 1
        async for dialog in main_client.iter_dialogs():
            if dialog.is_group:
                key = str(count)
                groups_map[key] = dialog
                groups[key] = dialog.name
                count += 1
        reply_markup = GroupsKeyboard(groups)
        await state.set_data({'groups': groups, 'page': 1})
        await SelectGroupState.GROUP_FROM.set()
        await bot.send_message(chat_id=chat_id, text='*Choose a group to scrape users from*',
                               parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
        group_from = await wait_for_state_value(state, 'group_from')
        group_to = await wait_for_state_value(state, 'group_to')
        group_from = groups_map[group_from]
        group_to = groups_map[group_to]
        #
        await bot.send_message(chat_id=chat_id, text=r'_Adding accounts to groups\._', parse_mode=ParseMode.MARKDOWN_V2)
        main_user = await main_client.get_me()
        # input_main_user = await main_client.get_input_entity(main_user.id)
        added_participants = set()
        async for user in main_client.iter_participants(group_to, aggressive=True):
            if not user.bot:
                added_participants.add(user.id)
        for acc in accounts[1:]:
            async with TgClient(acc) as client:
                user = await client.get_me()
                phone_contact = InputPhoneContact(client_id=user.id, phone=acc.phone,
                                                  first_name=acc.name, last_name=acc.name)
                await main_client(ImportContactsRequest(contacts=[phone_contact]))
                phone_contact = InputPhoneContact(client_id=main_user.id, phone=main_acc.phone,
                                                  first_name=main_acc.name, last_name=main_acc.name)
                await client(ImportContactsRequest([phone_contact]))
                input_user = await main_client.get_input_entity(user.id)
                input_group_from = await main_client.get_input_entity(group_from)
                input_group_to = await main_client.get_input_entity(group_to)
                try:
                    if group_from.is_channel:
                        await main_client(InviteToChannelRequest(channel=input_group_from, users=[input_user]))
                    else:
                        try:
                            await main_client(AddChatUserRequest(chat_id=input_group_from, user_id=input_user, fwd_limit=50))
                        except tg_errors.UserAlreadyParticipantError:
                            pass
                    if group_to.is_channel:
                        await main_client(InviteToChannelRequest(channel=input_group_to, users=[input_user]))
                    else:
                        try:
                            await main_client(AddChatUserRequest(chat_id=input_group_to, user_id=input_user, fwd_limit=50))
                        except tg_errors.UserAlreadyParticipantError:
                            pass
                except (tg_errors.UserKickedError, tg_errors.UserDeactivatedBanError,
                        tg_errors.UserBannedInChannelError, tg_errors.UserChannelsTooMuchError,
                        tg_errors.InputUserDeactivatedError, tg_errors.UserBlockedError) as e:
                    msg_map = {
                        'UserKickedError': r'_User *{}* was kicked from channel and cannot be added again\._'.format(escape_md(str(acc))),
                        'UserChannelsTooMuchError': r'_User *{}* is in too many channels\._'.format(escape_md(str(acc))),
                        'UserDeactivatedBanError': r'_User *{}* is deactivated\._'.format(escape_md(str(acc))),
                        'UserBannedInChannelError': r'_User *{}* is banned in channel\._'.format(escape_md(str(acc))),
                        'InputUserDeactivatedError': r'_User *{}* is deactivated\._'.format(escape_md(str(acc))),
                        'UserBlockedError': r'_User *{}* is blocked\._'.format(escape_md(str(acc)))
                    }
                    msg = msg_map[e.__class__.__name__]
                    await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN_V2)
                    continue
                except (tg_errors.ChatWriteForbiddenError, tg_errors.ChannelPrivateError,
                        tg_errors.ChatAdminRequiredError):
                    msg = r'_User *{}* do not have a permission to invite to selected groups\._'.format(str(acc))
                    await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN_V2)
                    await ScrapeState.MAIN.set()
                    await bot.send_message(chat_id=chat_id, text='Select mode', reply_markup=ScrapeKeyboard())
                    return
                client_group_from = await client.get_entity(group_from.id)
                client_group_to = await client.get_entity(group_to.id)
                added_participants = await add_participants(client, client_group_from, client_group_to, added_participants)
                delay = 3
                await asyncio.sleep(delay)
    await bot.send_message(chat_id=chat_id, text=r'_*Run completed\.*_', parse_mode=ParseMode.MARKDOWN_V2)
    await MenuState.MAIN.set()
    await bot.send_message(chat_id=chat_id, text='Menu', reply_markup=MainMenuKeyboard())

