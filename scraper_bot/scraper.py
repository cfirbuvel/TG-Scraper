import os

from telethon import TelegramClient, sync
from telethon.errors.rpcerrorlist import ApiIdInvalidError, PhoneCodeInvalidError, PhoneCodeExpiredError, \
    ChannelPrivateError
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from telethon.tl.types import InputChannel, InputPeerChannel, InputUser
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from telethon.tl.functions.channels import InviteToChannelRequest

from time import sleep


from bot_models import Account, db, reload_db
from bot_helpers import read_config, get_redis_key

# Telegram login


class BotResp:
    ACTION = 0
    MSG = 1
    EXIT = 2


def escape_markdown(msg):
    msg = msg.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
    return msg


def disconnect_clients(clients):
    for client in clients:
        client.disconnect()


def scrape_process(session):
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
        session_path = os.path.join(sessions_dir, 'session{}'.format(acc.id))
        client = TelegramClient(session_path, api_id, api_hash)
        client.connect()
        if not client.is_user_authorized():
            try:
                client.send_code_request(phone)
            except ApiIdInvalidError:
                msg = 'API id or hash is not valid for user _{}_\n' \
                      'User skipped.'.format(escape_markdown(acc.username))
                session.json_set('bot_msg', (BotResp.MSG, msg))
                continue
            msg = 'Enter the code for({})\n' \
                  'Please include spaces between numbers, e.g. _41 978_ (code expires otherwise):'.format(phone)
            session.json_set('bot_msg', (BotResp.ACTION, msg))
            code = get_redis_key(session, 'scraper_msg')
            code = code.replace(' ', '')
            try:
                client.sign_in(phone, code)
            except (PhoneCodeInvalidError, PhoneCodeExpiredError):
                msg = 'Phone code is not valid or expired for {}\n' \
                      'User skipped'.format(phone)
                session.json_set('bot_msg', (BotResp.MSG, msg))
                continue
        i += 1
        clients.append(client)
    if not clients:
        msg = 'Please add users before starting scrape'
        disconnect_clients(clients)
        session.json_set('bot_msg', (BotResp.EXIT, msg))
        return

    chats = []
    last_date = None
    chunk_size = 100
    groups = []
    targets = []
    result = clients[0](GetDialogsRequest(
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
    msg = 'List of groups:\n'
    i = 0
    for g in groups:
        msg += '{} - {}\n'.format(i, g.title)
        i += 1
    msg += 'Choose a group to scrape members from. (Enter a Number): '
    msg = escape_markdown(msg)

    session.json_set('bot_msg', (BotResp.ACTION, msg))
    g_index = get_redis_key(session, 'scraper_msg')
    chat_id_from = groups[int(g_index)].id

    i = 0
    msg = 'List of groups:\n'
    for g in targets:
        msg += '{} - {}\n'.format(i, g.title)
        i += 1
    msg += 'Choose a group or channel to add members. (Enter a Number): '
    msg = escape_markdown(msg)
    session.json_set('bot_msg', (BotResp.ACTION, msg))
    g_index = get_redis_key(session, 'scraper_msg')
    chat_id_to = targets[int(g_index)].id

    target_groups_from = []
    target_groups_to = []

    for client in clients:
        chats = []
        result = client(GetDialogsRequest(
            offset_date=last_date,
            offset_id=0,
            offset_peer=InputPeerEmpty(),
            limit=chunk_size,
            hash=0
        ))
        session.json_set('bot_msg', (BotResp.MSG, 'Scraping client _{}_ groups'.format(client.api_id)))
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
        disconnect_clients(clients)
        session.json_set('bot_msg', (BotResp.EXIT, msg))
        return
    groups_participants = []
    i = 0
    for client in clients:
        all_participants = []
        offset = 0
        limit = 100
        target_group = target_groups_from[i]
        group_title = escape_markdown(target_group.title)
        session.json_set('bot_msg', (BotResp.MSG, 'Scraping «{}» group participants'.format(group_title)))
        while True:
            try:
                participants = client(GetParticipantsRequest(
                    InputPeerChannel(target_group.id, target_group.access_hash),
                    ChannelParticipantsSearch(''), offset, limit, hash=0
                ))
            except ChannelPrivateError:
                error_msg = 'User _{}_ don\'t have an access to «{}» group. Skipping group'.format(client.api_id, group_title)
                session.json_set('bot_msg', (BotResp.MSG, error_msg))
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
    for user in groups_participants[0]:
        if user.id in memberIds:
            continue
        for usr in groups_participants[int(i % len(clients))]:
            if user.id == usr.id:
                userid = usr.id
                userhash = usr.access_hash
        try:
            msg = 'Adding {}'.format(userid)
            session.json_set('bot_msg', (BotResp.MSG, msg))
            clients[int(i % len(clients))](InviteToChannelRequest(
                InputChannel(target_groups_to[int(i % len(clients))].id,
                             target_groups_to[int(i % len(clients))].access_hash),
                [InputUser(userid, userhash)],
            ))
        except:
            pass
        i += 1
    disconnect_clients(clients)
    session.json_set('bot_msg', (BotResp.EXIT, 'Completed!'))
