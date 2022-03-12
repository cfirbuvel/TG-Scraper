import logging

from telethon.client import TelegramClient
from telethon.errors.rpcerrorlist import *
from telethon.helpers import _entity_type, _EntityType
from telethon.sessions.memory import MemorySession
from telethon.sessions.string import StringSession
# from telethon.errors.rpcerrorlist import ChatInvalidError
from telethon.tl.functions.contacts import GetBlockedRequest, UnblockRequest
from telethon.tl.functions.channels import GetParticipantsRequest, DeleteChannelRequest, JoinChannelRequest, \
    InviteToChannelRequest, GetParticipantRequest, LeaveChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest, DeleteChatRequest, CheckChatInviteRequest, \
    ImportChatInviteRequest, AddChatUserRequest
from telethon.tl.types import ChannelParticipantsSearch, ChatInviteAlready
from tortoise.exceptions import DoesNotExist
# from telethon.utils

from . import keyboards
from .bot import dispatcher
from .states import Scrape
from .utils import relative_sleep, is_channel


logger = logging.getLogger(__name__)


class IsBroadcastChannelError(Exception):
    pass


class TgClient(TelegramClient):

    def __init__(self, account, store_session=True, *args, **kwargs):
        self.account = account
        session = StringSession(string=account.session_string)
        self.store_session = store_session
        super().__init__(session, account.api_id, account.api_hash, *args, **kwargs)

    async def get_group_user(self, group, user):
        if _entity_type(group) == _EntityType.CHANNEL:
            try:
                res = await self(GetParticipantRequest(group, user))
            except:
                pass

    async def join_group(self, link):
        middle, end = link.strip().split('/')[-2:]
        if middle.lower() == 'joinchat' or end.startswith('+'):
            link = end.lstrip('+')
            invite = await self(CheckChatInviteRequest(link))
            if type(invite) == ChatInviteAlready:
                return invite.chat
            await relative_sleep(1.5)
            res = await self(ImportChatInviteRequest(link))
            res = res.chats[0]
        else:
            res = await self(JoinChannelRequest(link))
            res = res.chats[0]
            if res.broadcast:
                raise IsBroadcastChannelError()
        return res

    async def invite_to_group(self, user, entity):
        if is_channel(entity):
            try:
                await self(GetParticipantRequest(entity, user))
                raise UserAlreadyParticipantError('Temp.')
            except UserNotParticipantError:
                return await self(InviteToChannelRequest(channel=entity, users=[user]))
        else:
            await self(AddChatUserRequest(chat_id=entity.id, user_id=user.id, fwd_limit=50))

    async def get_participants(self, group, filter=ChannelParticipantsSearch('')):
        if _entity_type(group) == _EntityType.CHANNEL:
            users = []
            limit = 100
            offset = 0
            while True:
                # try:
                res = await self(GetParticipantsRequest(group, filter=filter, offset=offset, limit=limit, hash=0))
                # except (UserDeactivatedBanError, UserBannedInChannelError, UserBlockedError, UserKickedError) as e:
                #     logger.info(e)
                #     return
                if not res.users:
                    break
                users += res.users
                offset += len(res.users)
                await relative_sleep(0.5)
        else:
            full_chat = await self(GetFullChatRequest(group.id))
            users = full_chat.users
        return users

    async def clear_channels(self, free_slots=1):
        dialogs = await self.get_dialogs()
        dialogs = list(filter(lambda x: x.is_channel, dialogs))
        print('ACC {} LEN CHANNELS: '.format(self.account.name), len(dialogs))
        delete_num = (len(dialogs) + free_slots) - 500
        delete_num = max(0, delete_num)
        dialogs.reverse()
        for dialog in dialogs[:delete_num]:
            entity = dialog.entity
            if entity.creator:
                await self(DeleteChannelRequest(entity))
            else:
                await self(LeaveChannelRequest(entity))
            await relative_sleep(2.5)

    # async def burn_dialog(self, dialog):
    #     entity = dialog.entity
    #     if entity.creator:
    #         if _entity_type(entity) == _EntityType.CHAT:
    #             await self(DeleteChatRequest(entity.id))
    #         else:
    #             await self(DeleteChannelRequest(entity))
    #     else:
    #         await dialog.delete()

    async def clear_blocked(self):
        limit = 100
        offset = 0
        while True:
            blocked = await self(GetBlockedRequest(offset, limit))
            users = blocked.users
            if not users:
                return
            for user in users:
                await self(UnblockRequest(user))
                await relative_sleep(0.7)
            offset += len(users)

    async def save_session(self):
        try:
            await self.account.refresh_from_db()
        except DoesNotExist:
            return
        session_string = self.session.save()
        self.account.session_string = session_string
        await self.account.save()

    async def _tear_down(self):
        if self.store_session:
            await self.save_session()
        await self.disconnect()

    async def __aenter__(self):
        await self.connect()
        # await self.boot()
        return self

    async def __aexit__(self, *args):
        await self._tear_down()
