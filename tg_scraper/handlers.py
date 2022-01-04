import asyncio
from collections import defaultdict
import io
import json
import logging
import os
import random
import re
import shutil
import zipfile

from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import ContentTypeFilter, Regexp
from aiogram.types import Message, CallbackQuery
from aiogram.types.message import ContentType
from tortoise.exceptions import DoesNotExist

from . import tasks, keyboards
from .bot import dispatcher
from .conf import Settings
from .filters import CallbackData
from .models import Account
from .states import Menu, AddAccount, Accounts, SettingsState, Scrape
from .utils import Queue, task_running, session_db_to_string


logger = logging.getLogger(__name__)


async def to_main_menu(message, callback_query=None, callback_answer=None, edit=False):
    await Menu.main.set()
    params = {'text': 'Menu', 'reply_markup': keyboards.main_menu()}
    if edit:
        await message.edit_text(**params)
    else:
        await message.answer(**params)
    if callback_query:
        await callback_query.answer(text=callback_answer)


@dispatcher.message_handler(commands=['start'], state='*')
async def start(message: Message):
    await to_main_menu(message)


@dispatcher.callback_query_handler(CallbackData('add_acc'), state=(Menu.main, None))
async def add_acc(callback: CallbackQuery, state: FSMContext):
    await AddAccount.phone.set()
    await callback.message.edit_text('Please enter phone number', reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(state=AddAccount.phone)
async def add_user_enter_phone(message: Message, state: FSMContext):
    print(message.chat.id)
    phone = message.text.strip().replace(' ', '').replace('(', '').replace(')', '')
    logger.info('Phone entered')
    if not phone.lstrip('+').isdigit():
        await message.answer('Invalid phone format')
    elif await Account.filter(phone=phone).exists():
        await message.answer('Account with this phone number already exists')
    else:
        async with state.proxy() as user_data:
            user_data['add_user'] = {'phone': phone}
        await AddAccount.api_id.set()
        await message.answer('Please enter <b>API ID</b>', reply_markup=keyboards.cancel_back())
        return
    await message.answer('Please enter phone number', reply_markup=keyboards.back())


@dispatcher.callback_query_handler(CallbackData('back'), state=AddAccount.phone)
async def add_user_enter_phone_back(callback_query: CallbackQuery, state: FSMContext):
    await state.reset_data()
    await to_main_menu(callback_query.message, callback_query=callback_query, edit=True)


@dispatcher.message_handler(state=AddAccount.api_id)
async def add_user_enter_id(message: Message, state: FSMContext):
    api_id = message.text
    reply_markup = keyboards.cancel_back()
    if not api_id.isdigit():
        await message.answer('Please enter <b>API ID</b>\n<i>It should be a number</i>', reply_markup=reply_markup)
        return
    async with state.proxy() as user_data:
        user_data['add_user']['api_id'] = api_id
    await AddAccount.api_hash.set()
    await message.answer('Please enter <b>API hash</b>', reply_markup=reply_markup)


@dispatcher.callback_query_handler(CallbackData('back'), state=AddAccount.api_id)
async def add_user_enter_id_back(callback_query: CallbackQuery, state: FSMContext):
    await AddAccount.phone.set()
    await callback_query.message.edit_text('Please enter phone number', reply_markup=keyboards.back())
    await callback_query.answer()


@dispatcher.message_handler(state=AddAccount.api_hash)
async def add_user_enter_hash(message: Message, state: FSMContext):
    async with state.proxy() as user_data:
        user_data['add_user']['api_hash'] = message.text.strip()
    await AddAccount.name.set()
    await message.answer('Please enter account name', reply_markup=keyboards.cancel_back())


@dispatcher.callback_query_handler(CallbackData('back'), state=AddAccount.api_hash)
async def add_user_enter_hash_back(callback_query: CallbackQuery, state: FSMContext):
    await AddAccount.api_id.set()
    await callback_query.message.edit_text('Please enter *API ID*', reply_markup=keyboards.cancel_back())
    await callback_query.answer()


@dispatcher.message_handler(state=AddAccount.name)
async def add_user_enter_name(message: Message, state: FSMContext):
    async with state.proxy() as user_data:
        data = user_data['add_user']
        data['invites_max'] = random.randint(*Settings().invites_limit)
        await Account.create(name=message.text, **data)
    await message.answer(r'<i>Account has been created.</i>')
    await to_main_menu(message)


@dispatcher.callback_query_handler(CallbackData('back'), state=AddAccount.name)
async def add_user_enter_name_back(callback_query: CallbackQuery, state: FSMContext):
    await AddAccount.api_hash.set()
    await callback_query.message.edit_text('Please enter <b>API hash</b>', reply_markup=keyboards.cancel_back())
    await callback_query.answer()


@dispatcher.callback_query_handler(CallbackData('to_menu'), state=(AddAccount.api_id, AddAccount.api_hash, AddAccount.name,
                                                                   Accounts.list, SettingsState.main, Scrape.main))
async def add_user_cancel(callback_query: CallbackQuery, state: FSMContext):
    await state.reset_data()
    await to_main_menu(callback_query.message, callback_query=callback_query, edit=True)


@dispatcher.callback_query_handler(CallbackData('accounts'), state=(Menu.main, None))
async def accounts_menu(callback_query: CallbackQuery, state: FSMContext):
    await Accounts.list.set()
    accounts = await Account.all().values_list('id', 'name')
    await state.set_data({'list_page': 1})
    await callback_query.message.edit_text('Accounts', reply_markup=keyboards.accounts_list(accounts))
    await callback_query.answer()


@dispatcher.callback_query_handler(Regexp(r'^page_\d+$'), state=Accounts.list)
async def accounts_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split('_')[1])
    async with state.proxy() as user_data:
        old_page = user_data['list_page']
        if page != old_page:
            user_data['list_page'] = page
            accounts = await Account.all().values_list('id', 'name')
            await callback.message.edit_text('Accounts', reply_markup=keyboards.accounts_list(accounts, page))
    await callback.answer()


@dispatcher.callback_query_handler(Regexp(r'^\d+$'), state=Accounts.list)
async def accounts_select(callback: CallbackQuery, state: FSMContext):
    await Accounts.detail.set()
    acc = await Account.get(id=int(callback.data))
    await state.update_data({'acc_id': acc.id})
    await callback.message.edit_text(acc.get_detail_msg(), reply_markup=keyboards.account_detail())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('delete'), state=Accounts.detail)
async def account_delete(callback: CallbackQuery, state: FSMContext):
    await Accounts.delete.set()
    user_data = await state.get_data()
    acc = await Account.get(id=user_data['acc_id'])
    msg = 'Delete account <b>{}</b>?'.format(acc.safe_name)
    await callback.message.edit_text(msg, reply_markup=keyboards.yes_no())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('yes'), state=Accounts.delete)
async def account_delete_yes(callback: CallbackQuery, state: FSMContext):
    await Accounts.list.set()
    async with state.proxy() as user_data:
        acc_id = user_data['acc_id']
        del user_data['acc_id']
        page = user_data['list_page']
    acc = await Account.get(id=acc_id)
    await acc.delete()
    accounts = await Account.all().values_list('id', 'name')
    await callback.message.edit_text('Accounts', reply_markup=keyboards.accounts_list(accounts, page))
    await callback.answer('Deleted')


@dispatcher.callback_query_handler(CallbackData('no'), state=Accounts.delete)
async def account_delete_no(callback: CallbackQuery, state: FSMContext):
    await Accounts.detail.set()
    user_data = await state.get_data()
    acc = await Account.get(id=user_data['acc_id'])
    await callback.message.edit_text(acc.get_detail_msg(), reply_markup=keyboards.account_detail())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('set_main'), state=Accounts.detail)
async def on_account_set_main(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    acc = await Account.get(id=user_data['acc_id'])
    if not acc.master:
        await Account.filter(master=True).update(master=False)
        acc.master = True
        await acc.save()
        await callback.message.edit_text(acc.get_detail_msg(), reply_markup=keyboards.account_detail())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('back'), state=Accounts.detail)
async def account_detail_back(callback: CallbackQuery, state: FSMContext):
    await Accounts.list.set()
    page = (await state.get_data())['list_page']
    accounts = await Account.all().values_list('id', 'name')
    await callback.message.edit_text('Accounts', reply_markup=keyboards.accounts_list(accounts, page))
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('settings_menu', 'back'), state=(Menu.main, SettingsState.last_seen_filter,
                                                                                 SettingsState.join_delay,
                                                                                 SettingsState.run, None))
async def on_settings(callback: CallbackQuery, state: FSMContext):
    await SettingsState.main.set()
    await callback.message.edit_text(Settings().get_detail_msg(), reply_markup=keyboards.settings_menu())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('run', 'back'), state=(SettingsState.main, SettingsState.invites_limit,
                                                                       SettingsState.limit_reset))
async def on_run_settings(callback: CallbackQuery, state: FSMContext):
    await SettingsState.run.set()
    await callback.message.edit_text(Settings().get_run_settings_msg(), reply_markup=keyboards.run_settings())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('invites'), state=SettingsState.run)
async def on_invites_limit(callback: CallbackQuery, state: FSMContext):
    await SettingsState.invites_limit.set()
    msg = ('Enter range of numbers to choose randomly number of users one account can invite (50 max).\n'
           '<i>Current range: {}-{}</i>').format(*Settings().invites_limit)
    await callback.message.edit_text(msg, reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(state=SettingsState.invites_limit)
async def on_invites_limit_set(message: Message, state: FSMContext):
    await SettingsState.run.set()
    match = re.search(r'.*?(\d+).+?(\d+)', message.text)
    if match:
        value = (min(abs(int(digit)), 50) for digit in match.groups())
        value = tuple(sorted(value))
        if all(value):
            settings = Settings()
            if value != settings.invites_limit:
                settings.invites_limit = value
                await message.answer('Updating accounts with new limits.')
                for acc in await Account.all():
                    acc.invites_max = random.randint(*value)
                    await acc.save()
            await message.answer(settings.get_run_settings_msg(), reply_markup=keyboards.run_settings())
            return
    msg = ('🚫 Invalid value.\n'
           'Please enter two numbers separated by any symbol, e.g. <i>15-20</i>, <i>15 20</i> etc.\n'
           'Zero is prohibited.')
    await message.answer(msg, reply_markup=keyboards.back())


@dispatcher.callback_query_handler(CallbackData('reset'), state=SettingsState.run)
async def on_invites_reset(callback: CallbackQuery, state: FSMContext):
    await SettingsState.limit_reset.set()
    msg = ('Enter number of days passed before resetting limit (between 1 and 180).\n'
           '<i>Current number: {}</i>').format(Settings().limit_reset)
    await callback.message.edit_text(msg, reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(Regexp(r'^[\d\s]+$'), state=SettingsState.limit_reset)
async def on_invites_reset_set(message: Message, state: FSMContext):
    await SettingsState.run.set()
    value = abs(int(message.text))
    value = min(value, 180)
    settings = Settings()
    settings.limit_reset = value
    await message.answer(settings.get_run_settings_msg(), reply_markup=keyboards.run_settings())


@dispatcher.callback_query_handler(CallbackData('skip_sign_in'), state=SettingsState.run)
async def on_skip_sign_in_toggle(callback: CallbackQuery, state: FSMContext):
    settings = Settings()
    settings.skip_sign_in = not settings.skip_sign_in
    await callback.message.edit_reply_markup(reply_markup=keyboards.run_settings())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('last_seen_filter'), state=SettingsState.main)
async def on_last_seen_filter(callback: CallbackQuery, state: FSMContext):
    await SettingsState.last_seen_filter.set()
    msg = 'Select a last seen status to filter users by'
    await callback.message.edit_text(msg, reply_markup=keyboards.last_seen_filter())
    await callback.answer()


@dispatcher.callback_query_handler(Regexp(r'^\d+$'), state=SettingsState.last_seen_filter)
async def on_last_seen_filter_set(callback: CallbackQuery, state: FSMContext):
    choice = int(callback.data)
    settings = Settings()
    if settings.last_seen_filter != choice:
        settings.last_seen_filter = choice
        msg = 'Select a last seen status to filter users by'
        await callback.message.edit_text(msg, reply_markup=keyboards.last_seen_filter())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('join_delay'), state=SettingsState.main)
async def on_join_delay(callback: CallbackQuery, state: FSMContext):
    await SettingsState.join_delay.set()
    msg = ('Enter a delay in seconds between adding accounts.\n'
           '<i>(Small random offset will be added)</i>\n\n'
           'Current value: <b>{}</b> seconds.').format(Settings().join_delay)
    await callback.message.edit_text(msg, reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(Regexp(r'^[\s\d]+$'), state=SettingsState.join_delay)
async def on_join_delay_set(message: Message, state: FSMContext):
    await SettingsState.main.set()
    settings = Settings()
    settings.join_delay = int(message.text.replace(' ', '').replace('\n', ''))
    await message.answer(settings.get_detail_msg(), reply_markup=keyboards.settings_menu())


@dispatcher.callback_query_handler(CallbackData('add_sessions'), state=SettingsState.main)
async def add_sessions(callback: CallbackQuery, state: FSMContext):
    await SettingsState.add_sessions.set()
    await callback.message.edit_text('Please upload <b>.zip</b> archive with session files.', reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(content_types=ContentType.DOCUMENT, state=SettingsState.add_sessions)
async def add_sessions_upload(message: Message, state: FSMContext):
    file = io.BytesIO()
    await message.document.download(destination_file=file)
    added = 0
    try:
        archive = zipfile.ZipFile(file)
    except zipfile.BadZipfile:
        await message.answer('🚫 Invalid file.\n'
                             'Please upload solid <b>.zip</b> archive.')
        return
    await SettingsState.main.set()
    dirname = 'temp/{}'.format(message.chat.id)
    message = await message.answer('Creating accounts from sessions')
    task = asyncio.create_task(tasks.show_loading(message))
    if os.path.isdir(dirname):
        shutil.rmtree(dirname)
    os.makedirs(dirname, exist_ok=True)
    archive.extractall(path=dirname)
    sessions = defaultdict(dict)
    for dirpath, dirnames, filenames in os.walk(dirname):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            session_id, ext = os.path.splitext(filename)
            if ext == '.json':
                with open(filepath) as f:
                    data = json.load(f)
                name = ' '.join(filter(None, (data['first_name'], data['last_name']))).strip() or data['username'] or session_id
                data = {
                    'phone': data['phone'], 'api_id': data['app_id'],
                    'api_hash': data['app_hash'], 'name': name
                }
                sessions[session_id].update(data)
            elif ext == '.session':
                sessions[session_id]['session_string'] = await session_db_to_string(os.path.join(dirpath, filename))
    shutil.rmtree(dirname)
    settings = Settings()
    invites_limit = settings.invites_limit
    for data in sessions.values():
        if len(data) == 5:
            data['auto_created'] = True
            try:
                await Account.get(**data)
            except DoesNotExist:
                acc = Account(**data)
                acc.invites_max = random.randint(*invites_limit)
                await acc.save()
                added += 1
    task.cancel()
    await message.edit_text('Sessions have been processed <i>({} accounts created)</i>.'.format(added))
    await message.answer(settings.get_detail_msg(), reply_markup=keyboards.settings_menu())


@dispatcher.callback_query_handler(CallbackData('start_scrape'), state=(Menu.main, None))
async def on_start_scrape(callback: CallbackQuery, state: FSMContext):
    await Scrape.main.set()
    await callback.message.edit_text('Select mode', reply_markup=keyboards.start_scrape())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('once', 'repeatedly'), state=Scrape.main)
async def run_scrape(callback: CallbackQuery, state: FSMContext):
    message = callback.message
    chat_id = message.chat.id
    if task_running(chat_id):
        answer = None
        await Scrape.task_running.set()
        await message.edit_text('<b>Another task is running.</b>', reply_markup=keyboards.task_already_running())
    elif not await Account.exists():
        answer = 'Please add at least one account.'
    else:
        await state.reset_state()
        answer = '420!'
        queue = Queue()
        await state.set_data({'queue': queue})
        coroutine = {'once': tasks.scrape, 'repeatedly': tasks.scrape_repeatedly}[callback.data]
        asyncio.create_task(coroutine(chat_id, queue), name=str(chat_id))
        # if callback.data == 'once':
        #     asyncio.create_task(tasks.scrape(chat_id, state))
        # else:
        #     asyncio.create_task(tasks.scrape_repeatedly(chat_id, callback.bot, queue), name=str(chat_id))
    await callback.answer(answer)


# @dispatcher.callback_query_handler(CallbackData('stop_run'), state='*')
# async def stop_run(callback: CallbackQuery, state: FSMContext):
#     message = callback.message
#     for task in asyncio.all_tasks():
#         if task.get_name() == str(message.chat.id):
#             await message.delete()
#             await callback.answer('Stopping run.')
#             task.cancel()
#             await state.reset_state()
#             return
#     await message.edit_text('<b>There is no active run at the moment.</b>', reply_markup=None)
#     await callback.answer()
#     await to_main_menu(message)


@dispatcher.message_handler(commands=['stop'], state='*')
async def on_stop(message: Message, state: FSMContext):
    for task in asyncio.all_tasks():
        if task.get_name() == str(message.chat.id):
            await message.answer('Stopping run.')
            task.cancel()
            await state.reset_state()
            return
    await message.answer('There is no active task at the moment.')
    await to_main_menu(message)


@dispatcher.message_handler(Regexp(r'^[A-Za-z0-9_ ]+$'), state=Scrape.enter_code)
@dispatcher.callback_query_handler(CallbackData('resend', 'skip'), state=Scrape.enter_code)
async def on_code_request(update, state: FSMContext):
    await state.reset_state(with_data=False)
    if isinstance(update, Message):
        val = update.text.replace(' ', '')
    else:
        val = update.data
        await update.message.delete()
        await update.answer()
    queue = (await state.get_data())['queue']
    queue.put_nowait(val)
    await queue.join()


@dispatcher.callback_query_handler(Regexp(r'[0-9]+'), state=Scrape.group_from)
async def select_group_from(callback: CallbackQuery, state: FSMContext):
    # message = callback.message
    # TODO: Reset state when task stopped
    # if task_running(message.chat.id):
    key = callback.data
    async with state.proxy() as user_data:
        if 'groups' not in user_data:
            queue = user_data['queue']
            groups = queue.get_nowait()
            queue.task_done()
            user_data['groups'] = groups
        else:
            groups = user_data['groups']
        user_data['group_from'] = key
        user_data['list_page'] = 1
        del groups[key]
    await Scrape.group_to.set()
    reply_markup = keyboards.groups_list(list(groups.items()))
    await callback.message.edit_text('<b>Choose a group to add users to</b>', reply_markup=reply_markup)
    await callback.answer()
    # else:
    #     await state.reset_state()
    #     await message.delete()
    #     await callback.answer('Run has finished or stopped.')

# TODO: Add handler for groups pagination


@dispatcher.callback_query_handler(Regexp(r'[0-9]+'), state=Scrape.group_to)
async def select_group_to(callback: CallbackQuery, state: FSMContext):
    await state.reset_state(with_data=False)
    await callback.message.delete()
    # if task_running(message.chat.id):
    user_data = await state.get_data()
    queue = user_data['queue']
    # await Scrape.running.set()
    queue.put_nowait((user_data['group_from'], callback.data))
    await callback.answer()
    # else:
    #     await state.reset_state()
    #     await callback.answer('Run has finished or stopped.')


@dispatcher.callback_query_handler(Regexp(r'^page_\d+$'), state=(Scrape.group_from, Scrape.group_to))
async def select_group_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split('_')[1])
    async with state.proxy() as user_data:
        try:
            old_page = user_data['list_page']
        except KeyError:
            old_page = 1
        if page != old_page:
            if 'groups' not in user_data:
                queue = user_data['queue']
                groups = queue.get_nowait()
                queue.task_done()
                user_data['groups'] = groups
            else:
                groups = user_data['groups']
            user_data['list_page'] = page
            reply_markup = keyboards.groups_list(groups, page)
            await callback.message.edit_reply_markup(reply_markup=reply_markup)
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('blank'), state='*')
async def do_nothing(callback: CallbackQuery):
    await callback.answer()
