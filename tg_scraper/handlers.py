import asyncio
import logging
import operator

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import ContentTypeFilter, ForwardedMessageFilter, Regexp
from aiogram.types.message import ContentType
from aiogram.utils.markdown import markdown_decoration as md
from telethon.errors.rpcerrorlist import ApiIdInvalidError, PhoneNumberBannedError, FloodWaitError

from tg_scraper import Answer
from tg_scraper.bot import dp, lock
from tg_scraper.inline_keyboards import InlineKeyboard as Keyboard
from tg_scraper.models import Account, Settings
from tg_scraper.states import MenuState, AddAccountState, AccountsState, SettingsState, ScrapeState
from tg_scraper.pieces import main_menu
from tg_scraper.utils import Queue, QueryDataFilter, sign_msg, task_running
from tg_scraper.tasks import scrape_task, scrape_task_repeated


logger = logging.getLogger(__name__)


@dp.message_handler(commands=['start'], state='*')
async def start(message: types.Message):
    await main_menu(message)


@dp.callback_query_handler(QueryDataFilter('add_acc'), state=(MenuState.main, None))
async def add_acc(callback_query: types.CallbackQuery, state: FSMContext):
    await AddAccountState.phone.set()
    await callback_query.message.edit_text('Please enter phone number', reply_markup=Keyboard.back)
    await callback_query.answer()


@dp.message_handler(ContentTypeFilter(ContentType.TEXT), state=AddAccountState.phone)
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
        await AddAccountState.api_id.set()
        await message.answer('Please enter <b>API ID</b>', reply_markup=Keyboard.cancel_back)
        return
    await message.answer('Please enter phone number', reply_markup=Keyboard.back)


@dp.callback_query_handler(QueryDataFilter('back'), state=AddAccountState.phone)
async def add_user_enter_phone_back(callback_query: types.CallbackQuery, state: FSMContext):
    await state.reset_data()
    await main_menu(callback_query.message, callback_query=callback_query, edit=True)


@dp.message_handler(ContentTypeFilter(ContentType.TEXT), state=AddAccountState.api_id)
async def add_user_enter_id(message: types.Message, state: FSMContext):
    api_id = message.text
    reply_markup = Keyboard.cancel_back
    if not api_id.isdigit():
        await message.answer('Please enter <b>API ID</b>\n<i>It should be a number</i>', reply_markup=reply_markup)
        return
    async with state.proxy() as user_data:
        user_data['add_user']['api_id'] = api_id
    await AddAccountState.api_hash.set()
    await message.answer('Please enter <b>API hash</b>', reply_markup=reply_markup)


@dp.callback_query_handler(QueryDataFilter('back'), state=AddAccountState.api_id)
async def add_user_enter_id_back(callback_query: types.CallbackQuery, state: FSMContext):
    await AddAccountState.phone.set()
    await callback_query.message.edit_text('Please enter phone number', reply_markup=Keyboard.back)
    await callback_query.answer()


@dp.message_handler(ContentTypeFilter(ContentType.TEXT), state=AddAccountState.api_hash)
async def add_user_enter_hash(message: types.Message, state: FSMContext):
    async with state.proxy() as user_data:
        user_data['add_user']['api_hash'] = message.text.strip()
    await AddAccountState.name.set()
    await message.answer('Please enter account name', reply_markup=Keyboard.cancel_back)


@dp.callback_query_handler(QueryDataFilter('back'), state=AddAccountState.api_hash)
async def add_user_enter_hash_back(callback_query: types.CallbackQuery, state: FSMContext):
    await AddAccountState.api_id.set()
    await callback_query.message.edit_text('Please enter *API ID*', reply_markup=Keyboard.cancel_back)
    await callback_query.answer()


@dp.message_handler(ContentTypeFilter(ContentType.TEXT), state=AddAccountState.name)
async def add_user_enter_name(message: types.Message, state: FSMContext):
    async with state.proxy() as user_data:
        data = user_data['add_user']
        await Account.create(name=message.text, **data)
    await message.answer(r'<i>Account has been created.</i>')
    await main_menu(message)


@dp.callback_query_handler(QueryDataFilter('back'), state=AddAccountState.name)
async def add_user_enter_name_back(callback_query: types.CallbackQuery, state: FSMContext):
    await AddAccountState.api_hash.set()
    await callback_query.message.edit_text('Please enter <b>API hash</b>', reply_markup=Keyboard.cancel_back)
    await callback_query.answer()


@dp.callback_query_handler(
    QueryDataFilter('to_menu'),
    state=(AddAccountState.api_id, AddAccountState.api_hash, AddAccountState.name,
           AccountsState.list, SettingsState.main, ScrapeState.main)
)
async def add_user_cancel(callback_query: types.CallbackQuery, state: FSMContext):
    await state.reset_data()
    await main_menu(callback_query.message, callback_query=callback_query, edit=True)


@dp.callback_query_handler(QueryDataFilter('list_accs'), state=(MenuState.main, None))
async def accounts_menu(callback_query: types.CallbackQuery, state: FSMContext):
    await AccountsState.list.set()
    accounts = await Account.all()
    await callback_query.message.edit_text('Accounts', reply_markup=Keyboard.accounts(accounts))
    await callback_query.answer()


@dp.callback_query_handler(Regexp(r'[0-9]+'), state=AccountsState.list)
async def accounts_list(callback_query: types.CallbackQuery, state: FSMContext):
    await AccountsState.detail.set()
    id = int(callback_query.data)
    acc = await Account.filter(id=id).first()
    await state.update_data({'account_detail': {'id': id, 'name': acc.name}})
    await callback_query.message.edit_text(acc.get_detail_text(), reply_markup=Keyboard.account_detail)
    await callback_query.answer()


@dp.callback_query_handler(QueryDataFilter('delete'), state=AccountsState.detail)
async def account_delete(callback_query: types.CallbackQuery, state: FSMContext):
    await AccountsState.delete.set()
    data = (await state.get_data())['account_detail']
    msg = r'Delete *{}* account\?'.format(data['name'])
    await callback_query.message.edit_text(msg, reply_markup=Keyboard.yes_no)
    await callback_query.answer()


@dp.callback_query_handler(QueryDataFilter('yes'), state=AccountsState.delete)
async def account_delete_yes(callback_query: types.CallbackQuery, state: FSMContext):
    await state.reset_state(with_data=False)
    id = (await state.get_data())['account_detail']['id']
    acc = await Account.filter(id=id).first()
    await acc.delete()
    async with state.proxy() as user_data:
        del user_data['account_detail']
    await AccountsState.list.set()
    accounts = await Account.all()
    await callback_query.message.edit_text('Accounts', reply_markup=Keyboard.accounts(accounts))
    await callback_query.answer('Deleted')


@dp.callback_query_handler(QueryDataFilter('no'), state=AccountsState.delete)
async def account_delete_no(callback_query: types.CallbackQuery, state: FSMContext):
    await AccountsState.detail.set()
    id = (await state.get_data())['account_detail']['id']
    acc = await Account.filter(id=id).first()
    await callback_query.message.edit_text(acc.get_detail_text(), reply_markup=Keyboard.account_detail)
    await callback_query.answer()


@dp.callback_query_handler(QueryDataFilter('back'), state=AccountsState.detail)
async def account_detail_back(callback_query: types.CallbackQuery, state: FSMContext):
    await AccountsState.list.set()
    accounts = await Account.all()
    await callback_query.message.edit_text('Accounts', reply_markup=Keyboard.accounts(accounts))
    await callback_query.answer()


@dp.callback_query_handler(Regexp(r'^(settings|back)$'), state=(MenuState.main, SettingsState.status_filter, SettingsState.join_delay, None))
async def settings(callback_query: types.CallbackQuery, state: FSMContext):
    await SettingsState.main.set()
    settings = await Settings.get()
    await callback_query.message.edit_text(settings.details_msg(), reply_markup=Keyboard.settings)
    await callback_query.answer()


@dp.callback_query_handler(QueryDataFilter('status_filter'), state=SettingsState.main)
async def status_filter_setting(callback_query: types.CallbackQuery, state: FSMContext):
    await SettingsState.status_filter.set()
    settings = await Settings.get()
    msg = 'Select a last seen status to filter users by'
    await callback_query.message.edit_text(msg, reply_markup=Keyboard.status_filter(settings.status_filter.value))
    await callback_query.answer()


@dp.callback_query_handler(Regexp(r'[0-9]+'), state=SettingsState.status_filter)
async def status_filter_selected(callback_query: types.CallbackQuery, state: FSMContext):
    settings = await Settings.get()
    choice = int(callback_query.data)
    if settings.status_filter != choice:
        settings.status_filter = choice
        await settings.save()
        msg = 'Select a last seen status to filter users by'
        await callback_query.message.edit_text(msg, reply_markup=Keyboard.status_filter(settings.status_filter))
    await callback_query.answer()


@dp.callback_query_handler(QueryDataFilter('join_delay'), state=SettingsState.main)
async def join_delay_setting(callback_query: types.CallbackQuery, state: FSMContext):
    await SettingsState.join_delay.set()
    settings = await Settings.get()
    msg = ('Enter a delay in seconds between adding accounts.\n'
           '<i>(Small random offset will be added)</i>\n\n'
           'Current value: <b>{}</b> seconds.').format(settings.join_delay)
    await callback_query.message.edit_text(msg, reply_markup=Keyboard.back)
    await callback_query.answer()


@dp.message_handler(Regexp(r'^[\s0-9]+$'), ContentTypeFilter(ContentType.TEXT), state=SettingsState.join_delay)
async def join_delay_entered(message: types.Message, state: FSMContext):
    settings = await Settings.get()
    settings.join_delay = int(message.text.replace(' ', '').replace('\n', ''))
    await settings.save()
    await SettingsState.main.set()
    await message.answer(settings.details_msg(), reply_markup=Keyboard.settings)


@dp.callback_query_handler(QueryDataFilter('scrape'), state=(MenuState.main, None))
async def scrape(callback_query: types.CallbackQuery, state: FSMContext):
    await ScrapeState.main.set()
    await callback_query.message.edit_text('Select mode', reply_markup=Keyboard.scrape_menu)
    await callback_query.answer()


@dp.callback_query_handler(QueryDataFilter('run_scrape', 'run_scrape_daily'), state=ScrapeState.main)
async def run_scrape(callback_query: types.CallbackQuery, state: FSMContext):
    message = callback_query.message
    chat_id = message.chat.id
    if task_running(chat_id):
        answer = None
        await ScrapeState.running.set()
        await message.edit_text('<b>Another task is running.</b>', reply_markup=Keyboard.run_control)
    elif not await Account.exists():
        answer = 'Please add at least one account.'
    else:
        answer = '420!'
        queue = Queue()
        await state.set_data({'queue': queue})
        await message.delete()
        await ScrapeState.running.set()
        if callback_query.data == 'run_scrape':
            asyncio.create_task(scrape_task(chat_id, callback_query.bot, queue), name=str(chat_id))
        else:
            asyncio.create_task(scrape_task_repeated(chat_id, callback_query.bot, queue), name=str(chat_id))
    await callback_query.answer(answer)


# @dp.callback_query_handler(QueryDataFilter('run_scrape_daily'), state=ScrapeState.main)
# async def run_scrape_daily(callback_data: types.CallbackQuery, state: FSMContext):
#     pass


# @dp.message_handler(commands=['stop'], state='*')
@dp.callback_query_handler(QueryDataFilter(Answer.STOP), state='*')
async def stop_run(callback_query: types.CallbackQuery, state: FSMContext):
    message = callback_query.message
    for task in asyncio.all_tasks():
        if task.get_name() == str(message.chat.id):
            await state.reset_state()
            await message.delete()
            # await message.edit_text(sign_msg('<b>Terminating run.</b>'), reply_markup=None)
            await callback_query.answer('Stopping run.')
            task.cancel()
            return
    await message.edit_text('<b>There is no active run at the moment.</b>', reply_markup=None)
    await callback_query.answer()
    await main_menu(message)


@dp.message_handler(ContentTypeFilter(ContentType.TEXT), state=ScrapeState.enter_code)
async def enter_code(message: types.Message, state: FSMContext):
    if task_running(message.chat.id):
        code = message.text.replace(' ', '')
        await ScrapeState.running.set()
        queue = (await state.get_data())['queue']
        queue.put_nowait(Answer.CODE)
        await queue.join()
        queue.put_nowait(code)
    else:
        await state.reset_state()


@dp.callback_query_handler(QueryDataFilter(Answer.RESEND, Answer.SKIP), state=ScrapeState.enter_code)
async def enter_code_actions(callback_query: types.CallbackQuery, state: FSMContext):
    message = callback_query.message
    if task_running(message.chat.id):
        await ScrapeState.running.set()
        queue = (await state.get_data())['queue']
        queue.put_nowait(callback_query.data)
        await callback_query.message.delete()
        await callback_query.answer()
    else:
        await state.reset_state()
        await callback_query.message.delete()
        await callback_query.answer('There is no active run now.')


@dp.callback_query_handler(Regexp(r'[0-9]+'), state=ScrapeState.group_from)
async def select_group_from(callback_query: types.CallbackQuery, state: FSMContext):
    message = callback_query.message
    if task_running(message.chat.id):
        group_key = callback_query.data
        async with state.proxy() as user_data:
            if 'groups' not in user_data:
                queue = user_data['queue']
                groups = queue.get_nowait()
                queue.task_done()
                user_data['groups'] = groups
            else:
                groups = user_data['groups']
            user_data['group_from'] = group_key
            del groups[group_key]
        await ScrapeState.group_to.set()
        msg = '<b>Choose a group to add users to</b>'
        await message.edit_text(sign_msg(msg), reply_markup=Keyboard.groups(groups))
        await callback_query.answer()
    else:
        await state.reset_state()
        await message.delete()
        await callback_query.answer('Run has finished or stopped.')


@dp.callback_query_handler(Regexp(r'[0-9]+'), state=ScrapeState.group_to)
async def select_group_to(callback_query: types.CallbackQuery, state: FSMContext):
    message = callback_query.message
    await message.delete()
    if task_running(message.chat.id):
        user_data = await state.get_data()
        queue = user_data['queue']
        await ScrapeState.running.set()
        queue.put_nowait((user_data['group_from'], callback_query.data))
        await callback_query.answer()
    else:
        await state.reset_state()
        await callback_query.answer('Run has finished or stopped.')


@dp.callback_query_handler(QueryDataFilter(['prev', 'next']), state=(ScrapeState.group_from, ScrapeState.group_to))
async def select_group_page(callback_query: types.CallbackQuery, state: FSMContext):
    op_map = {'prev': operator.sub, 'next': operator.add}
    op = op_map[callback_query.data]
    async with state.proxy() as user_data:
        page = op(user_data['page'], 1)
        user_data['page'] = page
        if 'groups' not in user_data:
            queue = user_data['queue']
            groups = queue.get_nowait()
            queue.task_done()
            user_data['groups'] = groups
        else:
            groups = user_data['groups']
    await callback_query.message.edit_reply_markup(reply_markup=Keyboard.groups(groups, page=page))
    await callback_query.answer()
