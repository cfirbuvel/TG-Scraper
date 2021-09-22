from aiogram.bot.bot import Bot
from aiogram.utils.markdown import escape_md
from telethon.errors import rpcerrorlist as tg_errors

from tg_scraper.inline_keyboards import InlineKeyboard as Keyboard
from tg_scraper.states import MenuState, AddAccountState
from tg_scraper.utils import TgClient


# async def send_code(client: TgClient, bot: Bot, chat_id, state, msg_id=None):
#     acc = client.account
#     try:
#         sent_code = await client.send_code_request(acc.phone)
#         print('Code sent!!!')
#     except tg_errors.ApiIdInvalidError:
#         msg = 'API id or hash is not valid.'
#         await acc.set_invalid_details()
#     except tg_errors.PhoneNumberBannedError:
#         msg = 'Phone number is banned and cannot be used anymore.'
#         await acc.set_phone_banned()
#     except tg_errors.FloodWaitError as e:
#         msg = 'Account was banned for {} seconds (caused by code request)'.format(e.seconds)
#         await acc.set_flood_wait(e.seconds)
#     else:
#         # phone_hash = sent_code.phone_code_hash
#         # await state.update_data({'phone_code_hash': phone_hash})
#         await AccountState.ENTER_CODE.set()
#         if msg_id:
#             await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text='Code sent')
#         msg = ('Enter the code for *{} — {}*\n'
#                'Please divide it with whitespaces, for example: *41 9 78*').format(escape_md(acc.name), acc.phone)
#         await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN, reply_markup=EnterCodeKeyboard())
#         return sent_code.phone_code_hash
#     if msg_id:
#         await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=msg, parse_mode=ParseMode.MARKDOWN)
#     else:
#         await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
    # await MenuState.MAIN.set()
    # reply_markup = await MainMenuKeyboard.create()
    # await bot.send_message(chat_id=chat_id, text='Menu', reply_markup=reply_markup)


async def main_menu(message, callback_query=None, callback_answer=None, edit=False):
    await MenuState.MAIN.set()
    params = {'text': 'Menu', 'reply_markup': Keyboard.main_menu}
    if edit:
        await message.edit_text(**params)
    else:
        await message.answer(**params)
    if callback_query:
        await callback_query.answer(text=callback_answer)


async def show_loading():
    text = '♠️♦️♣️♥️'
