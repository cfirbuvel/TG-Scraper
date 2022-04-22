import logging

from telethon.client import TelegramClient
from telethon.errors.rpcerrorlist import *
from telethon.tl.functions.contacts import GetBlockedRequest, UnblockRequest
from telethon.tl.functions.channels import GetParticipantsRequest, DeleteChannelRequest, JoinChannelRequest, \
    LeaveChannelRequest, InviteToChannelRequest
from telethon.tl.types import ChannelParticipantsSearch, ChannelParticipantsRecent

from .utils import relative_sleep


logger = logging.getLogger(__name__)


class GroupInvalidError(Exception):

    def __init__(self, msg, *args):
        self.msg = msg
        super().__init__(msg, *args)


class CustomTelegramClient(TelegramClient):

    def __init__(self, session, api_id, api_hash, **kwargs):
        # self.account = account
        # session = StringSession(string=account.session_string)
        super().__init__(session, api_id, api_hash, **kwargs)

    # async def join_group(self, link):
    #     middle, end = link.strip().split('/')[-2:]
    #     if middle.lower() == 'joinchat' or end.startswith('+'):
    #         link = end.lstrip('+')
    #         invite = await self(CheckChatInviteRequest(link))
    #         if type(invite) == ChatInviteAlready:
    #             return invite.chat
    #         await relative_sleep(1.5)
    #         res = await self(ImportChatInviteRequest(link))
    #         res = res.chats[0]
    #     else:
    #         res = await self(JoinChannelRequest(link))
    #         res = res.chats[0]
    #         if res.broadcast:
    #             raise IsBroadcastChannelError()
    #     return res

    # # TODO: hash
    # async def get_users(self, channel, recent=False):
    #     if recent:
    #         filter = types.ChannelParticipantsRecent()
    #     else:
    #         filter = types.ChannelParticipantsSearch('')
    #     limit = 100
    #     offset = 0
    #     while True:
    #         participants = await self(GetParticipantsRequest(channel, filter=filter, offset=offset, limit=limit, hash=0))
    #         # except (UserDeactivatedBanError, UserBannedInChannelError, UserBlockedError, UserKickedError) as e:
    #         #     logger.info(e)
    #         #     return
    #         users = participants.users
    #         if not users:
    #             break
    #         offset += len(users)
    #         for user in users:
    #             yield user
    #         await relative_sleep(0.3)

    async def get_users(self, channel, offset, limit=100, recent=False):
        if recent:
            filter = ChannelParticipantsRecent()
        else:
            filter = ChannelParticipantsSearch('')
        res = await self(GetParticipantsRequest(channel, filter, offset, limit, hash=0))
        return res.users

    async def clear_channels(self, free_slots=1):
        dialogs = await self.get_dialogs()
        dialogs = list(filter(lambda x: x.is_channel, dialogs))
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

    async def join_group(self, link):
        while True:
            try:
                group = (await self(JoinChannelRequest(link))).chats[0]
            except ChannelsTooMuchError:
                await self.clear_channels(free_slots=10)
                continue
            except (ValueError, ChannelInvalidError):
                return
            if not group.broadcast:
                return group

    # TODO: Finish or not finish
    async def invite_to_channel(self, group, user):
        added = False
        try:
            resp = await self(InviteToChannelRequest(group, [user]))
        except (InputUserDeactivatedError, UserChannelsTooMuchError,
                UserNotMutualContactError, UserPrivacyRestrictedError):
            pass
        except PeerFloodError:
            pass
        # except FloodWaitError as ex:

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

    # async def save_session(self):
    #     session_string = self.session.save()
    #     self.account.session_string = session_string
    #     await self.account.save()

    async def __aenter__(self):
        await self.connect()
        # await self.boot()
        return self

    async def __aexit__(self, *args):
        # await self.save_session()
        await self.disconnect()
