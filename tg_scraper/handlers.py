import asyncio
import logging
import operator

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import ContentTypeFilter, ForwardedMessageFilter, Regexp
from aiogram.types.message import ContentType, ParseMode
from aiogram.utils.markdown import escape_md
from telethon import TelegramClient
from telethon.errors import rpcerrorlist as tg_errors
from telethon.sessions.string import StringSession

from tg_scraper.bot import dp
from tg_scraper.inline_keyboards import InlineKeyboard,\
    MainMenuKeyboard, BackKeyboard, CancelBackKeyboard, YesNoKeyboard, EnterCodeKeyboard, AccountsKeyboard, \
    ScrapeKeyboard, GroupsKeyboard
from tg_scraper.models import Account
from tg_scraper.states import MenuState, AccountState, ScrapeState, SelectGroupState
from tg_scraper.pieces import main_menu
from tg_scraper.utils import callback_query_filter, TgClient
from tg_scraper import tasks


logger = logging.getLogger(__name__)


@dp.message_handler(commands=['start'], state='*')
async def start(message: types.Message):
    await main_menu(message)


@dp.callback_query_handler(callback_query_filter('add_acc'), state=MenuState.MAIN)
async def add_acc(callback_query: types.CallbackQuery, state: FSMContext):
    await AccountState.PHONE.set()
    await callback_query.message.edit_text('Please enter phone number', reply_markup=BackKeyboard())
    await callback_query.answer()


@dp.message_handler(ContentTypeFilter(ContentType.TEXT), state=AccountState.PHONE)
async def add_user_enter_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip().replace(' ', '').replace('(', '').replace(')', '')
    logger.info('Phone entered')
    if not phone.lstrip('+').isdigit():
        await message.answer('Invalid phone format')
    elif await Account.filter(phone=phone).exists():
        await message.answer('Account with this phone number already exists')
    else:
        async with state.proxy() as user_data:
            user_data['add_user'] = {'phone': phone}
        await AccountState.API_ID.set()
        await message.answer('Please enter API Id', reply_markup=CancelBackKeyboard())
        return
    await message.answer('Please enter phone number', reply_markup=BackKeyboard())
# +972 53877 5948


@dp.message_handler(ContentTypeFilter(ContentType.TEXT), state=AccountState.API_ID)
async def add_user_enter_id(message: types.Message, state: FSMContext):
    api_id = message.text
    reply_markup = CancelBackKeyboard()
    if not api_id.isdigit():
        await message.answer('Please enter API Id\n'
                             '_It should be a number_', reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        return
    async with state.proxy() as user_data:
        user_data['add_user']['api_id'] = api_id
    await AccountState.API_HASH.set()
    await message.answer('Please enter API hash', reply_markup=reply_markup)


@dp.message_handler(ContentTypeFilter(ContentType.TEXT), state=AccountState.API_HASH)
async def add_user_enter_hash(message: types.Message, state: FSMContext):
    async with state.proxy() as user_data:
        user_data['add_user']['api_hash'] = message.text.strip()
    await AccountState.NAME.set()
    await message.answer('Please enter account name', reply_markup=CancelBackKeyboard())


@dp.message_handler(ContentTypeFilter(ContentType.TEXT), state=AccountState.NAME)
async def add_user_enter_name(message: types.Message, state: FSMContext):
    async with state.proxy() as user_data:
        data = user_data['add_user']
        await Account.create(name=message.text, **data)
    await message.answer(r'_Account has been created\._', parse_mode=ParseMode.MARKDOWN_V2)
    await main_menu(message)


@dp.callback_query_handler(callback_query_filter('back'), state=AccountState.NAME)
async def add_user_enter_name_back(callback_query: types.CallbackQuery, state: FSMContext):
    await main_menu(callback_query.message, callback_query, edit=True)


@dp.callback_query_handler(callback_query_filter('list_accs'), state=MenuState.MAIN)
async def accounts(callback_query: types.CallbackQuery, state: FSMContext):
    await AccountState.LIST.set()
    accounts = await Account.all()
    reply_markup = AccountsKeyboard(accounts)
    await callback_query.message.edit_text('Accounts', reply_markup=reply_markup)
    await callback_query.answer()


@dp.callback_query_handler(callback_query_filter('scrape'), state=MenuState.MAIN)
async def scrape(callback_query: types.CallbackQuery, state: FSMContext):
    await ScrapeState.MAIN.set()
    await callback_query.message.edit_text('Select mode', reply_markup=ScrapeKeyboard())
    await callback_query.answer()


# async def init_run(message, state):
#     async with state.proxy() as user_data:
#         data = user_data['run']
#         active = data['active']
#         failed = data['failed']
#         account_ids = active + failed
#         accounts = await Account.filter(id__not_in=account_ids)
#         for acc in accounts:
#             acc_session = AccountSession(acc)
#             client = TelegramClient(acc_session, acc.api_id, acc.api_hash)
#             await client.connect()
#             if await client.is_user_authorized():
#                 active.append(acc.id)
#             else:
#                 msg = 'Account *{} - {}*\n'.format(escape_md(acc.name), acc.phone)
#                 try:
#                     sent_code = await client.send_code_request(acc.phone)
#                 except (rpcerrorlist.ApiIdInvalidError, rpcerrorlist.PhoneNumberBannedError, rpcerrorlist.FloodWaitError):
#                     msg += 'API id or hash is not valid.'
#                     await acc.set_invalid_details()
#                 except rpcerrorlist.PhoneNumberBannedError:
#                     msg += 'Phone number is banned and cannot be used anymore.'
#                     await acc.set_phone_banned()
#                 except rpcerrorlist.FloodWaitError as e:
#                     msg += 'Account was banned for {} seconds (caused by code request)'.format(e.seconds)
#                     await acc.set_flood_wait(e.seconds)
#                 else:
#                     user_data['run']['current'] = acc.id
#                     user_data['run']['phone_code_hash'] = sent_code.phone_code_hash
#                     msg += 'Enter the confirmation code\n_(please divide it with whitespaces, for example: 41 978)_'
#                     await AccountState.ENTER_CODE.set()
#                     reply_markup = await EnterCodeKeyboard.create()
#                     await message.answer(msg, reply_markup=reply_markup)
#                     return
#                 await message.answer(msg)
#                 failed.append(acc.id)
#             await client.disconnect()
#
#         if active:
#             user_data['run']['active'] = active
#             acc = await Account.filter(id=active[0]).first()
#             client = TelegramClient(AccountSession(acc), acc.api_id, acc.api_hash)
#             await client.connect()
#             async for dialog in client.iter_dialogs():
#                 print(dialog)
#                 print(dir(dialog))
#                 print('\n')
#         else:


@dp.callback_query_handler(callback_query_filter('run_scrape'), state=ScrapeState.MAIN)
async def run_scrape(callback_query: types.CallbackQuery, state: FSMContext):
    if not await Account.exists():
        await callback_query.answer('Please add at least one account')
    else:
        await ScrapeState.RUNNING.set()
        await callback_query.answer('420!')
        asyncio.create_task(tasks.run_scrape(callback_query.bot, callback_query.message.chat.id, state))


@dp.message_handler(ContentTypeFilter(ContentType.TEXT), state=AccountState.ENTER_CODE)
async def enter_code(message: types.Message, state: FSMContext):
    # user_data = await state.get_data()
    # acc = await Account.filter(id=user_data['login_id']).first()
    # error_msg = None
    code = message.text.replace(' ', '')
    await ScrapeState.RUNNING.set()
    await state.set_data({'answer': 'code', 'login_code': code})
    # async with TgClient(acc) as client:
    #     try:
    #         await client.sign_in(acc.phone, code, phone_code_hash=user_data['phone_code_hash'])
    #     except tg_errors.PhoneCodeInvalidError:
    #         error_msg = 'Code is not valid'
    #     except tg_errors.PhoneCodeExpiredError:
    #         error_msg = 'Code has expired.'
    #     # else:
    #     #     await client.save_session()
    # if error_msg:
    #     await message.answer(error_msg, parse_mode=ParseMode.MARKDOWN, reply_markup=EnterCodeKeyboard())
    # else:
    #     await state.finish()
    #     await state.update_data({'signed_in': True})
    #     await message.answer('Signed in')


# @dp.callback_query_handler(callback_query_filter('skip'), state=AccountState.ENTER_CODE)
# async def skip_account(callback_query: types.CallbackQuery, state: FSMContext):
#     await state.finish()
#     await state.update_data({'signed_in': False})
#     await callback_query.message.edit_text('Skipped')
#     await callback_query.answer()


@dp.callback_query_handler(state=AccountState.ENTER_CODE)
async def resend_code(callback_query: types.CallbackQuery, state: FSMContext):
    await ScrapeState.RUNNING.set()
    await state.set_data({'answer': callback_query.data})
    await callback_query.answer()
    # user_data = await state.get_data()

    # acc = await Account.filter(id=user_data['login_id']).first()
    # async with TgClient(acc) as client:
    #     message = callback_query.message
    #     code_sent = await send_code(client, callback_query.bot, message.chat.id, state, msg_id=message.message_id)
    # if not code_sent:
    #     await state.update_data({'signed_in': False})
    # await callback_query.answer()


@dp.callback_query_handler(Regexp(r'[0-9]+'), state=SelectGroupState.GROUP_FROM)
async def select_group_from(callback_query: types.CallbackQuery, state: FSMContext):
    group_key = callback_query.data
    await callback_query.message.delete()
    async with state.proxy() as user_data:
        user_data['group_from'] = group_key
        del user_data['groups'][group_key]
        groups = user_data['groups']
    await callback_query.answer('Group set')
    reply_markup = GroupsKeyboard(groups)
    await SelectGroupState.GROUP_TO.set()
    await callback_query.message.answer('*Choose a group to add users to*', reply_markup=reply_markup,
                                        parse_mode=ParseMode.MARKDOWN_V2)


@dp.callback_query_handler(Regexp(r'[0-9]'), state=SelectGroupState.GROUP_TO)
async def select_group_to(callback_query: types.CallbackQuery, state: FSMContext):
    group_key = callback_query.data
    await ScrapeState.RUNNING.set()
    async with state.proxy() as user_data:
        user_data['group_to'] = group_key
        del user_data['groups']
    await callback_query.answer()


@dp.callback_query_handler(Regexp(r'(prev|next)'), state=SelectGroupState)
async def select_group_page(callback_query: types.CallbackQuery, state: FSMContext):
    op_map = {'prev': operator.sub, 'next': operator.add}
    op = op_map[callback_query.data]
    async with state.proxy() as user_data:
        page = op(user_data['page'], 1)
        user_data['page'] = page
        groups = user_data['groups']
    reply_markup = GroupsKeyboard(groups, page=page)
    await callback_query.message.edit_reply_markup(reply_markup=reply_markup)
    await callback_query.answer()


@dp.callback_query_handler(callback_query_filter('blank'), state='*')
async def answer_to_dummy(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()

