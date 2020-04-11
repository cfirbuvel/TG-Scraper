import asyncio
import datetime
import os
import time
import uuid
import random
import traceback
import sys
from collections import defaultdict

from telegram.ext import run_async
from telegram.utils.helpers import escape_markdown

from telethon import TelegramClient
from telethon.errors.rpcerrorlist import ApiIdInvalidError, PhoneCodeInvalidError, PhoneCodeExpiredError, \
    ChannelPrivateError, FloodWaitError, UserBannedInChannelError, UserPrivacyRestrictedError, \
    UserKickedError, ChatAdminRequiredError, PeerFloodError, ChatWriteForbiddenError, UserNotMutualContactError, \
    InputUserDeactivatedError, UserChannelsTooMuchError, UserBlockedError, AuthKeyDuplicatedError, UserDeactivatedBanError, \
    PhoneNumberBannedError
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from telethon.tl.types import InputChannel, InputPeerChannel, InputUser, InputPhoneContact
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from telethon.tl.functions.channels import InviteToChannelRequest, JoinChannelRequest
from telethon.tl.functions.contacts import ImportContactsRequest
from time import sleep

from bot_keyboards import action_keyboards_map
from bot_helpers import read_config, get_redis_key, set_bot_msg, get_exit_key, clear_session, SessionKeys
from bot_messages import BotMessages
from bot_models import Account, ScrapedAccount, Run, db
import logging
# logging.basicConfig(level=logging.INFO)
# # For instance, show only warnings and above
# logger = logging.getLogger('telethon')
# logger.setLevel(level=logging.INFO)
# hdlr = logging.FileHandler('./myapp.log')
# formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
# hdlr.setFormatter(formatter)
# logger.addHandler(hdlr)
# # Telegram login


class BotResp:
    MSG = 0
    EXIT = 1
    EDIT_MSG = 2


spinner_symbols = ['|', '/', '—', '\\']


async def disconnect_clients(clients):
    for client, acc, _ in clients:
        await client.disconnect()


async def send_confirmation_code(session, client, phone, username):
    try:
        await client.send_code_request(phone)
    except ApiIdInvalidError:
        msg = 'API id or hash is not valid for user _{}_\n' \
              'User skipped.'.format(escape_markdown(username))
        set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
        return
    except FloodWaitError:
        msg = 'User *{}* was banned for flood wait error'.format(escape_markdown(username))
        set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
        return
    except PhoneNumberBannedError:
        msg = 'User\'s *{}* phone number was banned and can\'t be used anymore'.format(escape_markdown(username))
        set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
        return
    return True


def enter_confirmation_code_action(phone, username, session):
    msg = 'Enter the code for({} - {})\n' \
          'Please include spaces between numbers, e.g. _41 978_ (code expires otherwise):'.format(phone, escape_markdown(username))
    set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'skip_user'})
    code = get_redis_key(session, SessionKeys.SCRAPER_MSG)
    if code not in ('❌ Cancel', 'Skip user'):
        code = code.replace(' ', '')
    return code
#
# Is it possible to know when an account finished his 50 users limit adding?
#
# Because sometimes accounts finish their limits before some other accounts, or if an account is blocked by telegram , the scraper still try to add clients from this accounts so many clients missed


async def stop_scrape(session, clients, msg=BotMessages.SCRAPE_CANCELLED):
    set_bot_msg(session, {'action': BotResp.EXIT, 'msg': msg})
    await disconnect_clients(clients)


def create_clients(loop):
    # loop = asyncio.get_event_loop()
    clients = []
    config = read_config('config.ini')
    sessions_dir = os.path.abspath(config['sessions_dir'])
    if not os.path.isdir(sessions_dir):
        os.mkdir(sessions_dir)
    for acc in Account.select():
        session_path = os.path.join(sessions_dir, '{}'.format(acc.phone))
        client = TelegramClient(session_path, acc.api_id, acc.api_hash, loop=loop)
        clients.append([client, acc, 0])
    return clients


async def scrape_specific_chat(session, scheduled_groups=False):
    loop = asyncio.get_event_loop()
    clients = []
    config = read_config('config.ini')
    sessions_dir = os.path.abspath(config['sessions_dir'])
    if not os.path.isdir(sessions_dir):
        os.mkdir(sessions_dir)
    for acc in Account.select():
        session_path = os.path.join(sessions_dir, '{}'.format(acc.phone))
        while True:
            client = TelegramClient(session_path, acc.api_id, acc.api_hash, loop=loop)
            try:
                await client.connect()
                clients.append((client, acc, 0))
                break
            except AuthKeyDuplicatedError:
                os.remove(session_path + '.session')
                journal_path = session_path + '.session-journal'
                if os.path.isfile(journal_path):
                    os.remove(journal_path)
    i = 0
    while True:
        try:
            client, acc, _ = clients[i]
        except IndexError:
            break
        is_authorized = await client.is_user_authorized()
        if not is_authorized:
            code_sent = await send_confirmation_code(session, client, acc.phone, acc.username)
            signed_in = False
            stop = False
            if code_sent:
                while True:
                    code = enter_confirmation_code_action(acc.phone, acc.username, session)
                    if code == '❌ Cancel':
                        stop = True
                    elif code != 'Skip user':
                        try:
                            await client.sign_in(acc.phone, code)
                            signed_in = True
                        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as ex:
                            if type(ex) == PhoneCodeExpiredError:
                                msg = 'Entered code for *{}* has expired.'
                            else:
                                msg = 'Entered code for *{}* is not valid.'
                            msg = msg.format(escape_markdown(acc.username))
                            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'phone_invalid'})
                            resp = get_redis_key(session, SessionKeys.SCRAPER_MSG)
                            if resp == 'Enter again':
                                continue
                            elif resp == 'Resend code':
                                code_sent = await send_confirmation_code(session, client, acc.phone, acc.username)
                                if code_sent:
                                    continue
                            elif resp == '❌ Cancel':
                                stop = True
                    break
            if stop:
                await stop_scrape(session, clients)
                return
            elif not signed_in:
                await client.disconnect()
                clients.pop(i)
                continue
        i += 1

    if not clients:
        msg = 'You either didn\'t add users or verification for all users failed'
        set_bot_msg(session, {'action': BotResp.EXIT, 'msg': msg})
        await disconnect_clients(clients)
        return


    groups = []
    targets = []
    first_client_index = 0
    first_client, first_client_acc, first_client_limit = clients[first_client_index]
    async for chat in first_client.iter_dialogs():
        try:
            chat = await first_client.get_entity(chat)
        except ChannelPrivateError:
            continue
        try:
            mgg = chat.megagroup
        except AttributeError:
            continue
        if mgg == True:
            if hasattr(chat, 'access_hash') and chat.access_hash is not None:
                groups.append(chat)
                targets.append(chat)
    sleep(1)

    if not scheduled_groups:
        msg = 'List of groups:\n'
        i = 0
        for g in groups:
            msg += '{} - {}\n'.format(i, g.title)
            if len(msg) > 3000:
                set_bot_msg(session, {'action': BotResp.MSG, 'msg': escape_markdown(msg)})
                msg = ''
            i += 1
        msg += 'Choose a group to scrape members from. (Enter a Number): '
        msg = escape_markdown(msg)
        set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})
        g_index = get_redis_key(session, SessionKeys.SCRAPER_MSG)
        if g_index == '❌ Stop':
            await stop_scrape(session, clients)
            return
        try:
            chat_from = groups[int(g_index)]
        except (ValueError, IndexError):
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': 'Invalid group number'})
            await disconnect_clients(clients)
            return
        chat_id_from = chat_from.id

        i = 0
        msg = 'List of groups:\n'
        for g in targets:
            msg += '{} - {}\n'.format(i, g.title)
            if len(msg) > 3000:
                set_bot_msg(session, {'action': BotResp.MSG, 'msg': escape_markdown(msg)})
                msg = ''
            i += 1
        msg += 'Choose a group or channel to add members. (Enter a Number): '
        msg = escape_markdown(msg)
        set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})
        g_index = get_redis_key(session, SessionKeys.SCRAPER_MSG)
        while True:
            if g_index == '❌ Stop':
                await stop_scrape(session, clients)
                return
            try:
                chat_to = targets[int(g_index)]
                break
            except (ValueError, IndexError):
                set_bot_msg(session, {'action': BotResp.MSG, 'msg': 'Invalid group number. Please enter again',
                                      'keyboard': 'stop_scrape'})
        chat_id_to = chat_to.id
        scheduled_groups = (chat_from, chat_to)
    else:
        chat_from, chat_to = scheduled_groups
        chat_id_from, chat_id_to = chat_from.id, chat_to.id

    try:
        run = Run.get(group_from=str(chat_id_from), group_to=str(chat_id_to))
    except Run.DoesNotExist:
        run = Run.create(group_from=str(chat_id_from), group_to=str(chat_id_to))

    msg = 'Adding bots to groups'
    set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})
    for counter, data in enumerate(clients[1:]):
        stop = session.json_get(SessionKeys.SCRAPER_MSG) == '❌ Stop'
        if stop:
            await stop_scrape(session, clients)
            return
        client, acc, limit = data
        name = str(counter)
        client_contact = InputPhoneContact(client_id=0, phone=acc.phone, first_name=name, last_name=name)
        try:
            await first_client(ImportContactsRequest([client_contact]))
        except PeerFloodError:
            j = 0
            msg = 'Got PeerFlood error. Waiting for 120 seconds. {}'.format(spinner_symbols[j])
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'edit': True})
            msg_id = get_redis_key(session, SessionKeys.SCRAPER_MSG)
            for i in range(120):
                time.sleep(1)
                j = (j + 1) % 4
                msg = 'Got PeerFlood error. Waiting for 120 seconds. {}'.format(spinner_symbols[j])
                set_bot_msg(session, {'action': BotResp.EDIT_MSG, 'msg': msg, 'edit': True, 'msg_id': msg_id})
                msg_id = get_redis_key(session, SessionKeys.SCRAPER_MSG)
        first_client_contact = InputPhoneContact(client_id=0, phone=first_client_acc.phone, first_name=name, last_name=name)
        await client(ImportContactsRequest([first_client_contact]))
        client_user = await client.get_me()
        client_user = await first_client.get_entity(client_user.id)
        try:
            await first_client(InviteToChannelRequest(
                chat_from,
                [client_user]
            ))
            first_client_limit += 1
            await first_client(InviteToChannelRequest(
                chat_to,
                [client_user]
            ))
            first_client_limit += 1
        except UserKickedError:
            msg = 'User _{}_ was kicked from channel and cannot be added again.'.format(acc.phone)
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
        except ChatWriteForbiddenError:
            msg = 'User _{}_ don\'t have permission to invite users to channels.'.format(acc.phone)
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
            break
        except UserChannelsTooMuchError:
            msg = 'User _{}_ is in too many channels.'.format(acc.phone)
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
        time.sleep(3)

    target_groups_from = []
    target_groups_to = []

    i = 0
    while True:
        try:
            client_data = clients[i]
        except IndexError:
            break
        client = client_data[0]
        msg = 'Scraping client _{}_ groups'.format(client.api_id)
        set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})
        group_from = None
        group_to = None
        async for chat in client.iter_dialogs():
            stop = session.json_get(SessionKeys.SCRAPER_MSG) == '❌ Stop'
            if stop:
                await stop_scrape(session, clients)
                return
            chat = chat.entity
            if not (hasattr(chat, 'megagroup') and hasattr(chat, 'access_hash')):
                continue
            if chat.access_hash is not None:
                if chat.id == chat_id_from:
                    group_from = chat
                elif chat.id == chat_id_to:
                    group_to = chat
        if group_from and group_to:
            target_groups_from.append(group_from)
            target_groups_to.append(group_to)
            i += 1
        else:
            acc = client_data[1]
            msg = 'Client {} wasn\'t added to groups. Skipping client'.format(escape_markdown(acc.username))
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
            await client.disconnect()
            del clients[i]
        sleep(1)


    offset = 0
    limit = 0
    memberIds = set()
    while True:
        try:
            participants = await first_client(GetParticipantsRequest(
                InputPeerChannel(target_groups_to[first_client_index].id, target_groups_to[first_client_index].access_hash),
                ChannelParticipantsSearch(''),
                offset, limit, hash=0
            ))
        except:
            break
        if not participants.users:
            break
        memberIds.update({member.id for member in participants.users})
        offset += len(participants.users)
        sleep(1)

    groups_participants = []

    added_participants = ScrapedAccount.select(ScrapedAccount.user_id)\
        .where(ScrapedAccount.run == run).tuples()
    added_participants = {val[0] for val in added_participants}
    added_participants.update(memberIds)

    i = 0
    while True:
        try:
            client, acc, limit = clients[i]
        except IndexError:
            break
        all_participants = {}
        offset = 0
        limit = 100
        target_group = target_groups_from[i]
        group_title = escape_markdown(target_group.title)
        j = 0
        msg = 'Scraping «{}» group participants for @{} {}'.format(group_title, escape_markdown(acc.username), spinner_symbols[j])
        set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'edit': True})
        msg_id = get_redis_key(session, SessionKeys.SCRAPER_MSG)
        while True:
            if msg_id == '❌ Stop':
                await stop_scrape(session, clients)
                return
            try:
                participants = await client(GetParticipantsRequest(
                    InputPeerChannel(target_group.id, target_group.access_hash),
                    ChannelParticipantsSearch(''), offset, limit, hash=0
                ))
            except ChannelPrivateError:
                error_msg = 'User _{}_ don\'t have an access to «{}» group. Skipping group'.format(client.api_id, group_title)
                set_bot_msg(session, {'action': BotResp.MSG, 'msg': error_msg})
                i -= 1
                await client.disconnect()
                clients.pop(i)
                break
            if not participants.users:
                break
            all_participants.update({user.id: user.access_hash for user in participants.users if user.id not in added_participants})
            offset += len(participants.users)
            sleep(1)
            j = (j + 1) % 4
            msg = 'Scraping «{}» group participants for @{} {}'.format(group_title, escape_markdown(acc.username),
                                                                       spinner_symbols[j])
            set_bot_msg(session, {'action': BotResp.EDIT_MSG, 'msg': msg, 'edit': True, 'msg_id': msg_id})
            msg_id = get_redis_key(session, SessionKeys.SCRAPER_MSG)
        groups_participants.append(all_participants)
        i += 1

    msg = 'Adding users to target group'
    set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})
    first_clients_participants = list(groups_participants[0].keys())
    i = 0
    while True:
        stop = session.json_get(SessionKeys.SCRAPER_MSG) == '❌ Stop'
        if stop:
            await stop_scrape(session, clients)
            return
        try:
            user_id = first_clients_participants[i]
        except IndexError:
            break
        if not len(clients):
            break

        p_i = int(i % len(clients))
        try:
            user_hash = groups_participants[p_i][user_id]
        except KeyError:
            i += 1
            continue

        client, acc, client_limit = clients[p_i]
        if client_limit >= 50:
            msg = 'Client {} has reached limit of 50 users.'.format(acc.phone)
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
            await client.disconnect()
            clients.pop(p_i)
            target_groups_to.pop(p_i)
            groups_participants.pop(p_i)
            continue
        msg = 'Adding {}'.format(user_id)
        set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
        try:
            await client(InviteToChannelRequest(
                InputChannel(target_groups_to[p_i].id,
                             target_groups_to[p_i].access_hash),
                [InputUser(user_id, user_hash)],
            ))
        except (FloodWaitError, UserBannedInChannelError, PeerFloodError, ChannelPrivateError, ChatWriteForbiddenError,
                UserKickedError) as ex:
            msg = 'Client {} can\'t add user. Client skipped.\n'.format(acc.phone)
            msg += 'Reason: {}'.format(ex)
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
            await client.disconnect()
            clients.pop(p_i)
            target_groups_to.pop(p_i)
            groups_participants.pop(p_i)
            continue
        except (UserPrivacyRestrictedError, UserNotMutualContactError, InputUserDeactivatedError, ChatAdminRequiredError,
                UserChannelsTooMuchError, UserBlockedError, UserChannelsTooMuchError, UserDeactivatedBanError) as ex:
            msg = 'Client {} can\'t add user.\n'.format(acc.phone)
            msg += 'Reason: {}'.format(ex)
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
        else:
            ScrapedAccount.create(user_id=user_id, run=run)
        time.sleep(3)
        i += 1
    await disconnect_clients(clients)
    return scheduled_groups


async def scrape_all_chats(session, scheduled_groups=False):
    loop = asyncio.get_event_loop()
    clients = []
    config = read_config('config.ini')
    sessions_dir = os.path.abspath(config['sessions_dir'])
    if not os.path.isdir(sessions_dir):
        os.mkdir(sessions_dir)
    for acc in Account.select():
        session_path = os.path.join(sessions_dir, '{}'.format(acc.phone))
        while True:
            client = TelegramClient(session_path, acc.api_id, acc.api_hash, loop=loop)
            try:
                await client.connect()
                clients.append((client, acc, 0))
                break
            except AuthKeyDuplicatedError:
                os.remove(session_path + '.session')
                journal_path = session_path + '.session-journal'
                if os.path.isfile(journal_path):
                    os.remove(journal_path)
    i = 0
    while True:
        try:
            client, acc, _ = clients[i]
        except IndexError:
            break
        is_authorized = await client.is_user_authorized()
        if not is_authorized:
            code_sent = await send_confirmation_code(session, client, acc.phone, acc.username)
            signed_in = False
            stop = False
            if code_sent:
                while True:
                    code = enter_confirmation_code_action(acc.phone, acc.username, session)
                    if code == '❌ Cancel':
                        stop = True
                    elif code != 'Skip user':
                        try:
                            await client.sign_in(acc.phone, code)
                            signed_in = True
                        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as ex:
                            if type(ex) == PhoneCodeExpiredError:
                                msg = 'Entered code for *{}* has expired.'
                            else:
                                msg = 'Entered code for *{}* is not valid.'
                            msg = msg.format(escape_markdown(acc.username))
                            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'phone_invalid'})
                            resp = get_redis_key(session, SessionKeys.SCRAPER_MSG)
                            if resp == 'Enter again':
                                continue
                            elif resp == 'Resend code':
                                code_sent = await send_confirmation_code(session, client, acc.phone, acc.username)
                                if code_sent:
                                    continue
                            elif resp == '❌ Cancel':
                                stop = True
                    break
            if stop:
                await stop_scrape(session, clients)
                return
            elif not signed_in:
                await client.disconnect()
                clients.pop(i)
                continue
        i += 1

    if not clients:
        msg = 'You either didn\'t add users or verification for all users failed'
        await stop_scrape(session, clients, msg)
        return

    all_chats = []
    i = 0
    while True:
        try:
            client, acc, _ = clients[i]
        except IndexError:
            break
        chats = []
        msg = 'Scraping client *{}* groups'.format(escape_markdown(acc.username))
        set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})
        async for chat in client.iter_dialogs():
            chat = chat.entity
            if not (hasattr(chat, 'megagroup') and hasattr(chat, 'access_hash')):
                continue
            chats.append(chat)
            stop = session.json_get(SessionKeys.SCRAPER_MSG) == '❌ Stop'
            if stop:
                await stop_scrape(session, clients)
                return
        all_chats.append(chats)
        i += 1

    if not scheduled_groups:
        i = 0
        msg = 'Choose a group to add members to. (Enter a Number):\n'
        for chat in all_chats[0]:
            msg += '{} - {}\n'.format(i, chat.title)
            if len(msg) > 3000:
                set_bot_msg(session, {'action': BotResp.MSG, 'msg': escape_markdown(msg)})
                msg = ''
            i += 1
        msg = escape_markdown(msg)
        set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})
        while True:
            g_index = get_redis_key(session, SessionKeys.SCRAPER_MSG)
            if g_index == '❌ Stop':
                await stop_scrape(session, clients)
                return
            try:
                chat_to = all_chats[0][int(g_index)]
                break
            except (ValueError, IndexError):
                set_bot_msg(session, {'action': BotResp.MSG, 'msg': 'Invalid group number. Please enter again',
                                      'keyboard': 'stop_scrape'})
        scheduled_groups = 'all', chat_to
    else:
        chat_to = scheduled_groups[1]

    try:
        run = Run.get(group_from='all', group_to=str(chat_to.id))
    except Run.DoesNotExist:
        run = Run.create(group_from='all', group_to=str(chat_to.id))

    msg = 'Adding clients to target group'
    set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})
    main_client, main_client_acc, main_client_limit = clients[0]
    main_client_contact = InputPhoneContact(client_id=0, phone=main_client_acc.phone, first_name=main_client_acc.phone,
                                            last_name=main_client_acc.phone)
    main_client_i = 1
    i = 1
    while True:
        stop = session.json_get(SessionKeys.SCRAPER_MSG) == '❌ Stop'
        if stop:
            await stop_scrape(session, clients)
            return
        if main_client_limit == 50:
            main_client, main_client_acc, main_client_limit = clients[main_client_i]
            main_client_contact = InputPhoneContact(client_id=0, phone=main_client_acc.phone,
                                                    first_name=main_client_acc.phone,
                                                    last_name=main_client_acc.phone)
            main_client_i += 1
        try:
            client, acc, _ = clients[i]
        except IndexError:
            break
        client_contact = InputPhoneContact(client_id=0, phone=acc.phone, first_name=acc.phone, last_name=acc.phone)
        try:
            await main_client(ImportContactsRequest([client_contact]))
            await client(ImportContactsRequest([main_client_contact]))
        except PeerFloodError:
            j = 0
            msg = 'Got PeerFlood error. Waiting for 120 seconds. {}'.format(spinner_symbols[j])
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'edit': True})
            msg_id = get_redis_key(session, SessionKeys.SCRAPER_MSG)
            for i in range(120):
                time.sleep(1)
                j = (j + 1) % 4
                msg = 'Got PeerFlood error. Waiting for 120 seconds. {}'.format(spinner_symbols[j])
                set_bot_msg(session,
                            {'action': BotResp.EDIT_MSG, 'msg': msg, 'edit': True, 'msg_id': msg_id})
                msg_id = get_redis_key(session, SessionKeys.SCRAPER_MSG)
        client_user = await client.get_me()
        client_user = await main_client.get_entity(client_user.id)
        try:
            await main_client(InviteToChannelRequest(chat_to, [client_user]))
            main_client_limit += 1
        except UserKickedError:
            msg = 'User _{}_ was kicked from channel and cannot be added again.'.format(acc.phone)
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
        except ChatWriteForbiddenError:
            msg = 'User _{}_ don\'t have permission to invite users to channels.'.format(acc.phone)
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
            break
        except UserChannelsTooMuchError:
            msg = 'User _{}_ is in too many channels.'.format(acc.phone)
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg})
        else:
            i += 1
            time.sleep(3)
            continue
        await client.disconnect()
        del clients[i]
        del all_chats[i]

    offset = 0
    limit = 0
    memberIds = set()
    while True:
        try:
            participants = await main_client(GetParticipantsRequest(
                InputPeerChannel(chat_to.id, chat_to.access_hash),
                ChannelParticipantsSearch(''),
                offset, limit, hash=0
            ))
        except:
            break
        if not participants.users:
            break
        memberIds.update({member.id for member in participants.users})
        offset += len(participants.users)
        sleep(1)

    all_chats = [[chat for chat in chats if chat.id != chat_to.id] for chats in all_chats]

    added_participants = ScrapedAccount.select(ScrapedAccount.user_id)\
        .where(ScrapedAccount.run == run).tuples()
    added_participants = {val[0] for val in added_participants}
    added_participants.update(memberIds)

    chats_participants = []
    all_participants = set()
    all_participants.update(added_participants)
    for i, client_data in enumerate(clients):
        client, acc, client_limit = client_data
        client_participants = []
        for chat in all_chats[i]:
            offset = 0
            limit = 50
            chat_title = escape_markdown(chat.title)
            j = 0
            msg = 'Scraping «{}» group participants for @{} {}'.format(chat_title, escape_markdown(acc.username), spinner_symbols[j])
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'edit': True})
            msg_id = get_redis_key(session, SessionKeys.SCRAPER_MSG)
            while True:
                if msg_id == '❌ Stop':
                    await stop_scrape(session, clients)
                    return
                try:
                    participants = await client(GetParticipantsRequest(
                        InputPeerChannel(chat.id, chat.access_hash),
                        ChannelParticipantsSearch(''), offset, limit, hash=0
                    ))
                except (ChannelPrivateError, ChatAdminRequiredError):
                    error_msg = 'User _{}_ don\'t have an access to «{}» group. Skipping group'.format(escape_markdown(acc.username), chat_title)
                    set_bot_msg(session, {'action': BotResp.MSG, 'msg': error_msg, 'keyboard': 'stop_scrape'})
                    break
                if not participants.users:
                    break
                for user in participants.users:
                    if user.id not in all_participants:
                        client_participants.append((user.id, user.access_hash))
                        all_participants.add(user.id)
                        client_limit += 1
                    if client_limit == 50:
                        break
                else:
                    offset += len(participants.users)
                    sleep(1)
                    j = (j + 1) % 4
                    msg = 'Scraping «{}» group participants for @{} {}'.format(chat_title,
                                                                               escape_markdown(acc.username),
                                                                               spinner_symbols[j])
                    set_bot_msg(session, {'action': BotResp.EDIT_MSG, 'msg': msg, 'edit': True, 'msg_id': msg_id})
                    msg_id = get_redis_key(session, SessionKeys.SCRAPER_MSG)
                    continue
                break
            if client_limit == 50:
                break
        chats_participants.append(client_participants)

    msg = 'Adding members to `{}` group.'.format(escape_markdown(chat_to.title))
    set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})

    i = 0
    while clients:
        stop = session.json_get(SessionKeys.SCRAPER_MSG) == '❌ Stop'
        if stop:
            await stop_scrape(session, clients)
            return

        i = i % len(clients)
        client_participants = chats_participants[i]
        try:
            user_id, user_access_hash = client_participants.pop()
        except IndexError:
            break
        client, acc, _ = clients[i]

        msg = 'Adding {}'.format(user_id)
        set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})
        try:
            channel = await client.get_entity(chat_to)
            await client(InviteToChannelRequest(
                channel,
                [InputUser(user_id, user_access_hash)]
            ))
        except (FloodWaitError, UserBannedInChannelError, PeerFloodError, ChannelPrivateError, ChatWriteForbiddenError,
                UserKickedError, UserDeactivatedBanError) as ex:
            msg = 'Client {} can\'t add user. Client skipped.\n'.format(acc.phone)
            msg += 'Reason: {}'.format(ex)
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})
            await client.disconnect()
            clients.pop(i)
            chats_participants.pop(i)
            continue
        except (UserPrivacyRestrictedError, UserNotMutualContactError, InputUserDeactivatedError, ChatAdminRequiredError,
                UserChannelsTooMuchError, UserBlockedError, UserChannelsTooMuchError) as ex:
            msg = 'Client {} can\'t add user.\n'.format(acc.phone)
            msg += 'Reason: {}'.format(ex)
            set_bot_msg(session, {'action': BotResp.MSG, 'msg': msg, 'keyboard': 'stop_scrape'})
        else:
            ScrapedAccount.create(user_id=user_id, run=run)
        time.sleep(3)
        i += 1
    await disconnect_clients(clients)
    return scheduled_groups


def delete_scraped_account(run_hash):
    ScrapedAccount.delete().where(ScrapedAccount.run_hash == run_hash).execute()


@run_async
def default_scrape(user_data, scrape_type='all'):
    session = user_data['session']
    loop = asyncio.new_event_loop()
    if scrape_type == 'all':
        loop.run_until_complete(scrape_all_chats(session))
    else:
        loop.run_until_complete(scrape_specific_chat(session))
    loop.close()
    msg = 'Completed!'
    set_bot_msg(session, {'action': BotResp.EXIT, 'msg': msg})
    session.json_set(SessionKeys.RUNNING, False)


@run_async
def scheduled_scrape(user_data, scrape_type='all', hours=24):
    seconds_per_hour = 3600
    seconds = hours * seconds_per_hour
    session = user_data['session']
    groups = None
    loop = asyncio.new_event_loop()
    while True:
        if scrape_type == 'all':
            groups = loop.run_until_complete(scrape_all_chats(session, scheduled_groups=groups))
        else:
            groups = loop.run_until_complete(scrape_specific_chat(session, scheduled_groups=groups))
        if not groups:
            session.json_set(SessionKeys.RUNNING, False)
            break
        now = datetime.datetime.now()
        next_time = now + datetime.timedelta(hours=24)
        next_time_str = next_time.strftime('%B %d, %H:%M')
        msg = 'Scrape completed. Next will be started at {}'.format(next_time_str)
        set_bot_msg(session, {'action': BotResp.EXIT, 'msg': msg})

        num_intervals = hours * 60
        interval_secs = seconds / num_intervals
        for _ in range(num_intervals):
            stop = get_exit_key(session)
            if stop:
                session.json_set(SessionKeys.RUNNING, False)
                break
            time.sleep(interval_secs)
    loop.close()

