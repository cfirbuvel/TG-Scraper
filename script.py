from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import PeerUser, PeerChat, PeerChannel, MessageEmpty, MessageService, InputChannel, \
    InputPeerChannel, InputUser
from telethon.tl.functions.messages import ForwardMessagesRequest
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from telethon.tl.functions.channels import InviteToChannelRequest
from time import sleep
from pprint import pprint
import json
import traceback

accounts_data = json.load(open('accounts.json'))
# Telegram login 
i = 0
clients = []
try:
    for acc in accounts_data['accounts']:
        api_id = acc['api_id']
        api_hash = acc['api_hash']
        phone = acc['phone']
        client = TelegramClient('session' + str(i), api_id, api_hash)
        client.connect()
        if not client.is_user_authorized():
            client.send_code_request(phone)
            client.sign_in(phone, input('Enter the code (' + phone + '): '))

        i += 1
        clients.append(client)
except SessionPasswordNeededError:
    pw = 'uXTFlgMK'
    client.sign_in(password=pw)

chats = []
last_date = None
chunk_size = 100
i = 0
groups = []
targets = []
while True:
    if i >= 1:
        break
    result = clients[0](GetDialogsRequest(
        offset_date=last_date,
        offset_id=0,
        offset_peer=InputPeerEmpty(),
        limit=chunk_size
    ))
    chats.extend(result.chats)
    if not result.messages:
        break
    for msg in chats:
        try:
            mgg = msg.megagroup
        except:
            continue
        if msg.megagroup == True:
            groups.append(msg)
        try:
            if msg.access_hash is not None:
                targets.append(msg)
        except:
            pass
    i += 1
    sleep(1)
# for c in chats:
# pprint(vars(c))
print('List of groups:')
i = 0
for g in groups:
    print(str(i) + '- ' + g.title)
    i += 1
g_index = input("Choose a group to scrape members from. (Enter a Number): ")
chat_id_from = groups[int(g_index)].id

i = 0
print('List of groups:')
i = 0
for g in targets:
    print(str(i) + '- ' + g.title)
    i += 1
g_index = input("Choose a group or channel to add members. (Enter a Number): ")
chat_id_to = targets[int(g_index)].id

target_groups_from = []
target_groups_to = []

for client in clients:
    # pprint(vars(client))
    chats = []
    i = 0
    while True:
        if i >= 1:
            break
        result = client(GetDialogsRequest(
            offset_date=last_date,
            offset_id=0,
            offset_peer=InputPeerEmpty(),
            limit=chunk_size
        ))
        chats.extend(result.chats)
        if not result.messages:
            break
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
        i += 1
        sleep(1)
if len(target_groups_from) != len(clients) or len(target_groups_to) != len(clients):
    print('All accounts should be a member of both groups.')
    exit()
groups_participants = []
i = 0
for client in clients:
    all_participants = []
    offset = 0
    limit = 100
    while True:
        participants = client.invoke(GetParticipantsRequest(
            InputPeerChannel(target_groups_from[i].id, target_groups_from[i].access_hash),
            ChannelParticipantsSearch(''), offset, limit, hash=0
        ))
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
        participants = client.invoke(GetParticipantsRequest(
            InputPeerChannel(target_groups_to[i].id, target_groups_to[i].access_hash), ChannelParticipantsSearch(''),
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
        print('Adding ' + str(userid))
        clients[int(i % len(clients))].invoke(InviteToChannelRequest(
            InputChannel(target_groups_to[int(i % len(clients))].id,
                         target_groups_to[int(i % len(clients))].access_hash),
            [InputUser(userid, userhash)],
        ))
    except:
        # traceback.print_exc()
        pass
    i += 1
print('Completed.')
