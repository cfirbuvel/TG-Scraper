from telethon.client import TelegramClient
from telethon.errors.rpcerrorlist import (FloodWaitError,  ApiIdInvalidError, PhoneNumberBannedError,
                                          PhoneNumberUnoccupiedError, PhoneCodeInvalidError, PhoneCodeExpiredError)
from telethon.sessions.string import StringSession
from telethon.tl.types import TypeUser

from . import keyboards
from .bot import dispatcher
from .conf import Settings
from .states import Scrape
from .utils import exc_to_msg


class NotAuthenticatedError(Exception):
    pass


class TgClient(TelegramClient):

    def __init__(self, account, *args, **kwargs):
        self.account = account
        session = StringSession(string=account.session_string)
        # self.chat_id = kwargs.pop('chat_id')
        # self.queue = kwargs.pop('queue')
        # session = AccountSession(account)
        super().__init__(session, account.api_id, account.api_hash, *args, **kwargs)

    # async def boot(self):
    #     await self.connect()
    #     if not await self.is_user_authorized():
    #         if settings_menu.skip_sign_in:
    #             raise NotAuthenticatedError()
    #         bot = dispatcher.bot
    #         acc = self.account
    #         await bot.send_message(self.chat_id, 'Signing in <b>{}</b>'.format(acc.safe_name))
    #         code = None
    #         while True:
    #             try:
    #                 res = await self.sign_in(acc.phone, code)
    #             except (ApiIdInvalidError, PhoneNumberBannedError, FloodWaitError, PhoneNumberUnoccupiedError) as e:
    #                 await bot.send_message(self.chat_id, exc_to_msg(e), disable_web_page_preview=True)
    #                 if type(e) in (ApiIdInvalidError, PhoneNumberBannedError):
    #                     await acc.delete()
    #                     await bot.send_message(self.chat_id, 'Account has been deleted.')
    #                 raise NotAuthenticatedError()
    #             except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
    #                 msg = ('{}\n'
    #                        'You can reenter code.\n'
    #                        '<i>Keep in mind that after several attempts Telegram might'
    #                        ' temporarily block account from signing in .</i>').format(exc_to_msg(e))
    #             else:
    #                 if isinstance(res, TypeUser):
    #                     return
    #                 msg = ('Code was sent to <b>{}</b>\n'
    #                        'Please divide it with whitespaces, like: <i>41 9 78</i>').format(acc.safe_name)
    #             await Scrape.enter_code.set()
    #             await bot.send_message(self.chat_id, msg, reply_markup=keyboards.code_request())
    #             answer = await self.queue.get()
    #             self.queue.task_done()
    #             if answer == 'skip':
    #                 raise NotAuthenticatedError()
    #             if answer == 'resend':
    #                 code = None
    #             else:
    #                 code = answer

    async def save_session(self):
        session_string = self.session.save()
        self.account.session_string = session_string
        await self.account.save()

    async def __aenter__(self):
        await self.connect()
        # await self.boot()
        return self

    async def __aexit__(self, *args):
        await self.save_session()
        await self.disconnect()
