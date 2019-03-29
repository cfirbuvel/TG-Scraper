import datetime
import os
import time
import uuid
import random

from telegram.ext import run_async
from telegram.utils.helpers import escape_markdown

from telethon import TelegramClient, sync
from telethon.errors.rpcerrorlist import ApiIdInvalidError, PhoneCodeInvalidError, PhoneCodeExpiredError, \
    ChannelPrivateError, FloodWaitError, UserBannedInChannelError, ChannelInvalidError, UserPrivacyRestrictedError, \
    UserKickedError, ChatAdminRequiredError, PeerFloodError, ChatWriteForbiddenError, UserNotMutualContactError
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

from pprint import pprint

# Telegram login


class BotResp:
    ACTION = 0
    MSG = 1
    EXIT = 2


def disconnect_clients(clients):
    for client, _, _ in clients:
        client.disconnect()


def print_attrs(o):
    for attr in dir(o):
        if not attr.startswith('_'):
            try:
                print(attr, ':', getattr(o, attr))
            except:
                pass


def send_confirmation_code(session, client, phone, username):
    try:
        client.send_code_request(phone)
    except ApiIdInvalidError:
        msg = 'API id or hash is not valid for user _{}_\n' \
              'User skipped.'.format(escape_markdown(username))
        set_bot_msg(session, BotResp.MSG, msg)
        return
    except FloodWaitError:
        msg = 'User *{}* was banned for flood wait error'.format(escape_markdown(username))
        set_bot_msg(session, BotResp.MSG, msg)
        return
    code = enter_confirmation_code_action(phone, session)
    return code


def enter_confirmation_code_action(phone, session):
    msg = 'Enter the code for({})\n' \
          'Please include spaces between numbers, e.g. _41 978_ (code expires otherwise):'.format(phone)
    set_bot_msg(session, BotResp.ACTION, msg, 'stop_scrape')
    code = get_redis_key(session, SessionKeys.SCRAPER_MSG)
    if code == '❌ Stop':
        code = None
    else:
        code = code.replace(' ', '')
    return code


def send_code_sign_in(client, session, phone, username, code=None):
    if not code:
        code = send_confirmation_code(session, client, phone, username)
    if code is None:
        return
    try:
        client.sign_in(phone, code)
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as ex:
        if type(ex) == PhoneCodeExpiredError:
            msg = 'Entered code for *{}* has expired.'
        else:
            msg = 'Entered code for *{}* is not valid.'
        msg = msg.format(escape_markdown(username))
        session.json_set(SessionKeys.BOT_MSG, (BotResp.ACTION, msg, 'phone_invalid'))
        resp = get_redis_key(session, SessionKeys.SCRAPER_MSG)
        if resp == 'Enter again':
            code = enter_confirmation_code_action(phone, session)
            if code is None:
                return
            return send_code_sign_in(client, session, phone, username, code)
        elif resp == 'Resend code':
            return send_code_sign_in(client, session, phone, username)
        elif resp == 'Skip user':
            return 'continue'
        elif resp == '❌ Cancel':
            return
    return True

#
# Is it possible to know when an account finished his 50 users limit adding?
#
# Because sometimes accounts finish their limits before some other accounts, or if an account is blocked by telegram , the scraper still try to add clients from this accounts so many clients missed


def stop_scrape(session, clients, msg=BotMessages.SCRAPE_CANCELLED):
    set_bot_msg(session, BotResp.EXIT, msg)
    disconnect_clients(clients)
    session.json_set(SessionKeys.RUNNING, False)


def scrape_process(session, scheduled_groups=False):
    i = 0
    clients = []
    config = read_config('config.ini')
    sessions_dir = os.path.abspath(config['sessions_dir'])
    if not os.path.isdir(sessions_dir):
        os.mkdir(sessions_dir)
    for acc in Account.select():
        api_id = acc.api_id
        api_hash = acc.api_hash
        phone = acc.phone
        session_path = os.path.join(sessions_dir, '{}'.format(phone))
        client = TelegramClient(session_path, api_id, api_hash)
        client.connect()
        username = acc.username
        if not client.is_user_authorized():
            resp = send_code_sign_in(client, session, phone, username)
            if resp == 'continue':
                continue
            elif resp is None:
                stop_scrape(session, clients)
                return
        i += 1
        clients.append([client, phone, 0])
    if not clients:
        msg = 'You either didn\'t add users or verification for all users failed'
        stop_scrape(session, clients, msg)
        return

    chats = []
    last_date = None
    chunk_size = 100
    groups = []
    targets = []
    first_client_index = 0
    first_client, first_client_phone, first_client_limit = clients[first_client_index]
    result = first_client(GetDialogsRequest(
        offset_date=last_date,
        offset_id=0,
        offset_peer=InputPeerEmpty(),
        limit=chunk_size,
        hash=0
    ))
    chats.extend(result.chats)
    if result.messages:
        for msg in chats:
            try:
                mgg = msg.megagroup
            except:
                continue
            if mgg == True:
                groups.append(msg)
            try:
                if msg.access_hash is not None:
                    targets.append(msg)
            except:
                pass
    sleep(1)

    if not scheduled_groups:
        msg = 'List of groups:\n'
        i = 0
        for g in groups:
            msg += '{} - {}\n'.format(i, g.title)
            i += 1
        msg += 'Choose a group to scrape members from. (Enter a Number): '
        msg = escape_markdown(msg)
        set_bot_msg(session, BotResp.ACTION, msg, 'stop_scrape')
        g_index = get_redis_key(session, SessionKeys.SCRAPER_MSG)
        if g_index == '❌ Stop':
            stop_scrape(session, clients)
            return

        try:
            chat_from = groups[int(g_index)]
        except (ValueError, IndexError):
            set_bot_msg(session, BotResp.MSG, 'Invalid group number')
            stop_scrape(session, clients)
            return
        chat_id_from = chat_from.id

        i = 0
        msg = 'List of groups:\n'
        for g in targets:
            msg += '{} - {}\n'.format(i, g.title)
            i += 1
        msg += 'Choose a group or channel to add members. (Enter a Number): '
        msg = escape_markdown(msg)
        set_bot_msg(session, BotResp.ACTION, msg, 'stop_scrape')
        g_index = get_redis_key(session, SessionKeys.SCRAPER_MSG)
        if g_index == '❌ Stop':
            stop_scrape(session, clients)
            return

        try:
            chat_to = targets[int(g_index)]
        except (ValueError, IndexError):
            set_bot_msg(session, BotResp.MSG, 'Invalid group number')
            stop_scrape(session, clients)
            return

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
    set_bot_msg(session, BotResp.MSG, msg)
    for counter, data in enumerate(clients[1:]):
        client, phone, limit = data
        name = str(counter)
        client_contact = InputPhoneContact(client_id=0, phone=phone, first_name=name, last_name=name)
        first_client(ImportContactsRequest([client_contact]))
        first_client_contact = InputPhoneContact(client_id=0, phone=first_client_phone, first_name=name, last_name=name)
        client(ImportContactsRequest([first_client_contact]))
        client_user = client.get_me()
        client_user = first_client.get_entity(client_user.id)
        try:
            first_client(InviteToChannelRequest(
                chat_from,
                [client_user]
            ))
            first_client_limit += 1
            first_client(InviteToChannelRequest(
                chat_to,
                [client_user]
            ))
            first_client_limit += 1
        except UserKickedError:
            msg = 'User _{}_ was kicked from channel and cannot be added again.'.format(phone)
            set_bot_msg(session, BotResp.MSG, msg)
        except ChatWriteForbiddenError:
            msg = 'User _{}_ don\'t have permission to invite users to channels.'.format(phone)
            set_bot_msg(session, BotResp.MSG, msg)
            break

    target_groups_from = []
    target_groups_to = []

    for i, client_data in enumerate(clients):
        client = client_data[0]
        chats = []
        result = client(GetDialogsRequest(
            offset_date=last_date,
            offset_id=0,
            offset_peer=InputPeerEmpty(),
            limit=chunk_size,
            hash=0
        ))
        msg = 'Scraping client _{}_ groups'.format(client.api_id)
        set_bot_msg(session, BotResp.MSG, msg)
        chats.extend(result.chats)
        if result.messages:
            for chat in chats:
                if not hasattr(chat, 'megagroup'):
                    continue
                try:
                    if chat.access_hash is not None:
                        if chat.id == chat_id_from:
                            target_groups_from.append(chat)
                        elif chat.id == chat_id_to:
                            target_groups_to.append(chat)
                except:
                    pass

        sleep(1)

    if len(target_groups_from) != len(clients) or len(target_groups_to) != len(clients):
        msg = 'All accounts should be members of both groups.'
        stop_scrape(session, clients, msg)
        return

    offset = 0
    limit = 0
    memberIds = set()
    while True:
        try:
            participants = first_client(GetParticipantsRequest(
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
            client = clients[i][0]
        except IndexError:
            break
        all_participants = {}
        offset = 0
        limit = 100
        target_group = target_groups_from[i]
        group_title = escape_markdown(target_group.title)
        msg = 'Scraping «{}» group participants'.format(group_title)
        set_bot_msg(session, BotResp.MSG, msg)
        while True:
            try:
                participants = client(GetParticipantsRequest(
                    InputPeerChannel(target_group.id, target_group.access_hash),
                    ChannelParticipantsSearch(''), offset, limit, hash=0
                ))
            except ChannelPrivateError:
                error_msg = 'User _{}_ don\'t have an access to «{}» group. Skipping group'.format(client.api_id, group_title)
                set_bot_msg(session, BotResp.MSG, error_msg)
                clients.pop(i)
                break
            if not participants.users:
                break
            all_participants.update({user.id: user.access_hash for user in participants.users if user.id not in added_participants})
            offset += len(participants.users)
            sleep(1)
        groups_participants.append(all_participants)
        i += 1

    first_clients_participants = list(groups_participants[0].keys())
    i = 0
    while True:
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

        client, phone, client_limit = clients[p_i]
        if client_limit >= 50:
            msg = 'Client {} has reached limit of 50 users.'.format(phone)
            set_bot_msg(session, BotResp.MSG, msg)
            clients.pop(p_i)
            target_groups_to.pop(p_i)
            groups_participants.pop(p_i)
            continue
        msg = 'Adding {}'.format(user_id)
        set_bot_msg(session, BotResp.MSG, msg)
        try:
            client(InviteToChannelRequest(
                InputChannel(target_groups_to[p_i].id,
                             target_groups_to[p_i].access_hash),
                [InputUser(user_id, user_hash)],
            ))
        except (FloodWaitError, UserBannedInChannelError, PeerFloodError, ChatAdminRequiredError, ChannelPrivateError) as ex:
            msg = 'Client {} can\'t add user. Client skipped.\n'.format(phone)
            msg += 'Reason: {}'.format(ex)
            set_bot_msg(session, BotResp.MSG, msg)
            clients.pop(p_i)
            target_groups_to.pop(p_i)
            groups_participants.pop(p_i)
            continue
        except (UserPrivacyRestrictedError, UserNotMutualContactError) as ex:
            msg = 'Client {} can\'t add user.\n'.format(phone)
            msg += 'Reason: {}'.format(ex)
            set_bot_msg(session, BotResp.MSG, msg)
        else:
            acc = ScrapedAccount.create(user_id=user_id, run=run)
            print('acc created')
            print(acc.user_id)
        i += 1
    disconnect_clients(clients)
    return scheduled_groups


def delete_scraped_account(run_hash):
    ScrapedAccount.delete().where(ScrapedAccount.run_hash == run_hash).execute()


@run_async
def default_scrape(user_data):
    session = user_data['session']
    scrape_process(session)
    msg = 'Completed!'
    set_bot_msg(session, BotResp.EXIT, msg)
    session.json_set(SessionKeys.RUNNING, False)

@run_async
def scheduled_scrape(user_data, hours=24):
    seconds_per_hour = 3600
    seconds = hours * seconds_per_hour
    session = user_data['session']
    groups = None
    while True:
        groups = scrape_process(session, scheduled_groups=groups)
        if not groups:
            return

        now = datetime.datetime.now()
        next_time = now + datetime.timedelta(hours=24)
        next_time_str = next_time.strftime('%B %d, %H:%M')
        msg = 'Scrape completed. Next will be started at {}'.format(next_time_str)
        set_bot_msg(session, BotResp.EXIT, msg)

        num_intervals = hours * 60
        interval_secs = seconds / num_intervals
        for _ in range(num_intervals):
            stop = get_exit_key(session)
            if stop:
                session.json_set(SessionKeys.RUNNING, False)
                return
            time.sleep(interval_secs)


