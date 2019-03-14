import datetime
import os
import time
import uuid

from telethon import TelegramClient, sync
from telethon.errors.rpcerrorlist import ApiIdInvalidError, PhoneCodeInvalidError, PhoneCodeExpiredError, \
    ChannelPrivateError, FloodWaitError
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from telethon.tl.types import InputChannel, InputPeerChannel, InputUser, InputPhoneContact
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from telethon.tl.functions.channels import InviteToChannelRequest, JoinChannelRequest
from telethon.tl.functions.contacts import ImportContactsRequest

from time import sleep

from bot_keyboards import action_keyboards_map
from bot_helpers import read_config, get_redis_key, set_bot_msg, escape_markdown, get_exit_key, clear_session, SessionKeys
from bot_messages import BotMessages
from bot_models import Account, ScrapedAccount, Run, db


# Telegram login


class BotResp:
    ACTION = 0
    MSG = 1
    EXIT = 2


def disconnect_clients(clients):
    for client, _, _ in clients:
        client.disconnect()


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
    if not code:
        return 'continue'
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
            if not code:
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


def stop_scrape(session, clients, run, msg=BotMessages.SCRAPE_CANCELLED):
    set_bot_msg(session, BotResp.EXIT, msg)
    disconnect_clients(clients)
    if not run:
        session.json_set(SessionKeys.RUNNING, False)


def scrape_process(user_data, run=None):
    session = user_data['session']
    i = 0
    clients = []
    config = read_config('config.ini')
    sessions_dir = os.path.abspath(config['sessions_dir'])
    if not os.path.isdir(sessions_dir):
        os.mkdir(sessions_dir)
    for acc in Account.select():
        api_id = acc.api_id
        api_hash = acc.api_hash
        session_path = os.path.join(sessions_dir, 'session{}'.format(acc.id))
        client = TelegramClient(session_path, api_id, api_hash)
        client.connect()
        phone = acc.phone
        username = acc.username
        if not client.is_user_authorized():
            resp = send_code_sign_in(client, session, phone, username)
            if resp == 'continue':
                continue
            elif resp is None:
                stop_scrape(session, clients, run)
                return
        i += 1
        clients.append([client, phone, 0])
    if not clients:
        msg = 'You either didn\'t add users or verification for all users failed'
        stop_scrape(session, clients, run, msg)
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
        for group, target in zip(groups, targets):
            if first_client_limit == 50:
                clients[first_client_index][2] = first_client_limit
                first_client, first_client_phone, first_client_limit = clients[first_client_index + 1]
            first_client(InviteToChannelRequest(
                group,
                [client_user]
            ))
            first_client(InviteToChannelRequest(
                group,
                [client_user]
            ))
            first_client_limit += 2

            # client(JoinChannelRequest(group))
            # client(JoinChannelRequest(target))
    g_index = None
    if run:
        g_index = run.group_from
    if g_index is None:
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
            stop_scrape(session, clients, run)
            return
        g_index = int(g_index)
        if run:
            run.group_from = g_index
            run.save()

    chat_id_from = groups[g_index].id

    g_index = None
    if run:
        g_index = run.group_to
    if g_index is None:
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
            stop_scrape(session, clients, run)
            return
        g_index = int(g_index)
        if run:
            run.group_to = g_index
            run.save()

    chat_id_to = targets[g_index].id

    target_groups_from = []
    target_groups_to = []

    for client, _, _ in clients:
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
            for msg in chats:
                try:
                    mgg = msg.megagroup
                except:
                    continue
                try:
                    if msg.access_hash is not None:
                        if msg.id == chat_id_from:
                            target_groups_from.append(msg)
                        if msg.id == chat_id_to:
                            target_groups_to.append(msg)
                except:
                    pass
        sleep(1)
    if len(target_groups_from) != len(clients) or len(target_groups_to) != len(clients):
        msg = 'All accounts should be a member of both groups.'
        stop_scrape(session, clients, run, msg)
        return
    groups_participants = []
    i = 0
    if run:
        added_participants = ScrapedAccount.select(ScrapedAccount.user_id)\
            .where(ScrapedAccount.run == run).tuples()
        added_participants = [val[0] for val in added_participants]
    for client, _, _ in clients:
        all_participants = []
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
                break
            if not participants.users:
                break
            all_participants.extend(participants.users)
            offset += len(participants.users)
            sleep(1)
        i += 1
        groups_participants.append(all_participants)
    try:
        i = 0
        offset = 0
        limit = 0
        members = []
        while True:
            participants = client(GetParticipantsRequest(
                InputPeerChannel(target_groups_to[i].id, target_groups_to[i].access_hash),
                ChannelParticipantsSearch(''),
                offset, limit, hash=0
            ))
            if not participants.users:
                break
            members.extend(participants.users)
            offset += len(participants.users)
            sleep(1)
        memberIds = []
        for member in members:
            memberIds.append(member.id)
    except:
        memberIds = []
        pass

    i = 0
    counter = 0
    first_clients_participants = groups_participants[0]
    users_len = len(first_clients_participants)
    while True:
        if counter == users_len:
            break
        user = first_clients_participants[counter]
        if user.id in memberIds:
            continue
        p_i = int(i % len(clients))
        for usr in groups_participants[p_i]:
            if user.id == usr.id:
                user_id = usr.id
                user_hash = usr.access_hash
                if run:
                    if user_id in added_participants:
                        counter += 1
                        i += 1
                        continue
        try:
            client, _, client_limit = clients[p_i]
            if client_limit >= 50:
                i += 1
                continue
            msg = 'Adding {}'.format(user_id)
            set_bot_msg(session, BotResp.MSG, msg)
            client(InviteToChannelRequest(
                InputChannel(target_groups_to[int(i % len(clients))].id,
                             target_groups_to[int(i % len(clients))].access_hash),
                [InputUser(user_id, user_hash)],
            ))
        except FloodWaitError:
            pass
        else:
            ScrapedAccount.create(user_id=user_id, run=run)
        i += 1
        counter += 1
    disconnect_clients(clients)
    if run:
        now = datetime.datetime.now()
        next_time = now + datetime.timedelta(hours=24)
        next_time_str = next_time.strftime('%B %d, %H:%M')
        msg = 'Scrape completed. Next will be started at {}'.format(next_time_str)
        set_bot_msg(session, BotResp.EXIT, msg)
    else:
        msg = 'Completed!'
        set_bot_msg(session, BotResp.EXIT, msg)
        session.json_set(SessionKeys.RUNNING, False)
    return True


def delete_scraped_account(run_hash):
    ScrapedAccount.delete().where(ScrapedAccount.run_hash == run_hash).execute()


def scheduled_scrape(user_data, hours=24):
    run_hash = uuid.uuid4().hex
    run = Run.create(run_hash=run_hash)
    seconds_per_hour = 3600
    seconds = hours * seconds_per_hour
    session = user_data['session']
    while True:
        res = scrape_process(user_data, run)
        if not res:
            run.delete_instance()
            session.json_set(SessionKeys.RUNNING, False)
            return
        num_intervals = hours * 60
        interval_secs = seconds / num_intervals
        for _ in range(num_intervals):
            stop = get_exit_key(session)
            if stop:
                run.delete_instance()
                session.json_set(SessionKeys.RUNNING, False)
                return
            time.sleep(interval_secs)


