import asyncio
import functools
from collections import defaultdict
import io
import json
import logging
import os
import random
import re
import shutil
from urllib.parse import urlsplit
import zipfile

from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import ContentTypeFilter, Regexp
from aiogram.types import Message, CallbackQuery
from aiogram.types.message import ContentType
from tortoise.expressions import F
from tortoise.exceptions import DoesNotExist
import validators

from . import tasks, keyboards
from .bot import dispatcher
from .conf import settings
from .filters import CallbackData
from .models import Account, Group
from .states import Menu, AddAccount, Accounts, Settings, Scrape
from .utils import Queue, task_running, session_db_to_string, update_accounts_limits


logger = logging.getLogger(__name__)


async def to_main_menu(message, callback_query=None, callback_answer=None, edit=False):
    await Menu.main.set()
    params = {'text': 'Main', 'reply_markup': keyboards.main_menu()}
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
        await message.answer('🚫 Invalid phone format')
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
        data['invites_max'] = random.randint(*settings.invites_limit)
        await Account.create(name=message.text, **data)
    await message.answer(r'<i>Account has been created.</i>')
    await to_main_menu(message)


@dispatcher.callback_query_handler(CallbackData('back'), state=AddAccount.name)
async def add_user_enter_name_back(callback_query: CallbackQuery, state: FSMContext):
    await AddAccount.api_hash.set()
    await callback_query.message.edit_text('Please enter <b>API hash</b>', reply_markup=keyboards.cancel_back())
    await callback_query.answer()


@dispatcher.callback_query_handler(CallbackData('to_menu'), state=(AddAccount.api_id, AddAccount.api_hash, AddAccount.name,
                                                                   Accounts.list, Settings.main, Scrape.main))
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


@dispatcher.callback_query_handler(CallbackData('settings_menu', 'back'), state=(Menu.main, Settings.last_seen_filter,
                                                                                 Settings.join_delay,
                                                                                 Settings.run, None))
async def on_settings(callback: CallbackQuery, state: FSMContext):
    await Settings.main.set()
    await callback.message.edit_text(settings.get_detail_msg(), reply_markup=keyboards.settings_menu())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('run', 'back'), state=(Settings.main, Settings.invites_limit,
                                                                       Settings.limit_reset))
async def on_run_settings(callback: CallbackQuery, state: FSMContext):
    await Settings.run.set()
    await callback.message.edit_text(settings.get_run_settings_msg(), reply_markup=keyboards.run_settings())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('invites'), state=Settings.run)
async def on_invites_limit(callback: CallbackQuery, state: FSMContext):
    await Settings.invites_limit.set()
    msg = ('Enter range of numbers to choose randomly number of users one account can invite (50 max).\n'
           '<i>Current range: {}-{}</i>').format(*settings.invites_limit)
    await callback.message.edit_text(msg, reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(state=Settings.invites_limit)
async def on_invites_limit_set(message: Message, state: FSMContext):
    await Settings.run.set()
    match = re.search(r'.*?(\d+).+?(\d+)', message.text)
    if match:
        value = (min(abs(int(digit)), 50) for digit in match.groups())
        value = tuple(sorted(value))
        if all(value):
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


@dispatcher.callback_query_handler(CallbackData('reset'), state=Settings.run)
async def on_invites_reset(callback: CallbackQuery, state: FSMContext):
    await Settings.limit_reset.set()
    msg = ('Enter number of days passed before resetting limit (between 1 and 180).\n'
           '<i>Current number: {}</i>').format(settings.limit_reset)
    await callback.message.edit_text(msg, reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(Regexp(r'^[\d\s]+$'), state=Settings.limit_reset)
async def on_invites_reset_set(message: Message, state: FSMContext):
    await Settings.run.set()
    value = abs(int(message.text))
    value = min(value, 180)
    settings.limit_reset = value
    await message.answer(settings.get_run_settings_msg(), reply_markup=keyboards.run_settings())


# @dispatcher.callback_query_handler(CallbackData('skip_sign_in'), state=Settings.run)
# async def on_skip_sign_in_toggle(callback: CallbackQuery, state: FSMContext):
#     settings.skip_sign_in = not settings.skip_sign_in
#     await callback.message.edit_reply_markup(reply_markup=keyboards.run_settings())
#     await callback.answer()


@dispatcher.callback_query_handler(CallbackData('last_seen_filter'), state=Settings.main)
async def on_last_seen_filter(callback: CallbackQuery, state: FSMContext):
    await Settings.last_seen_filter.set()
    msg = 'Select a last seen status to filter users by'
    await callback.message.edit_text(msg, reply_markup=keyboards.last_seen_filter())
    await callback.answer()


@dispatcher.callback_query_handler(Regexp(r'^\d+$'), state=Settings.last_seen_filter)
async def on_last_seen_filter_set(callback: CallbackQuery, state: FSMContext):
    choice = int(callback.data)
    if settings.last_seen_filter != choice:
        settings.last_seen_filter = choice
        msg = 'Select a last seen status to filter users by'
        await callback.message.edit_text(msg, reply_markup=keyboards.last_seen_filter())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('join_delay'), state=Settings.main)
async def on_join_delay(callback: CallbackQuery, state: FSMContext):
    await Settings.join_delay.set()
    msg = ('Enter interval for joining a group in seconds.\n'
           '<i>(Small random offset will be added)</i>\n\n'
           'Current value: <b>{}</b> seconds.').format(settings.join_delay)
    await callback.message.edit_text(msg, reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(Regexp(r'^[\s\d]+$'), state=Settings.join_delay)
async def on_join_delay_set(message: Message, state: FSMContext):
    await Settings.main.set()
    settings.join_delay = int(message.text.replace(' ', '').replace('\n', ''))
    await message.answer(settings.get_detail_msg(), reply_markup=keyboards.settings_menu())


@dispatcher.callback_query_handler(CallbackData('add_sessions'), state=Settings.main)
async def add_sessions(callback: CallbackQuery, state: FSMContext):
    await Settings.add_sessions.set()
    await callback.message.edit_text('Please upload <b>.zip</b> archive with session files.', reply_markup=keyboards.back())
    await callback.answer()


# TODO: seems that file sessions are not cleared
@dispatcher.message_handler(content_types=ContentType.DOCUMENT, state=Settings.add_sessions)
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
    await Settings.main.set()
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
    await message.edit_text('Sessions have been users_processed <i>({} accounts created)</i>.'.format(added))
    await message.answer(settings.get_detail_msg(), reply_markup=keyboards.settings_menu())


@dispatcher.callback_query_handler(CallbackData('scrape'), state=(Menu.main, None))
async def on_scrape(callback: CallbackQuery, state: FSMContext):
    await Scrape.main.set()
    await callback.message.edit_text('💥 Scrape', reply_markup=keyboards.scrape_menu())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('groups'), state=Scrape.main)
async def on_groups(callback: CallbackQuery, state: FSMContext):
    await Scrape.groups.set()
    await callback.message.edit_text('🔗 Groups', reply_markup=keyboards.groups())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('add'), state=Scrape.groups)
async def on_add_group(callback: CallbackQuery, state: FSMContext):
    await Scrape.add_group.set()
    await callback.message.edit_text('Please enter group invite link.', reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(state=Scrape.add_group)
async def on_add_group_link(message: Message, state: FSMContext):
    link = message.text.strip()
    parts = urlsplit(link)
    if not parts.scheme:
        link = 'https://' + link
    if not validators.url(link):
        msg = '🚫 Not a valid URL. Please enter correct URL.'
    elif await Group.exists(link=link):
        msg = '🚫 Group with this link already exists. Please enter another value.'
    else:
        await Group.create(link=link)
        await Scrape.groups.set()
        await message.answer('✔️ Added group.')
        await message.answer('🔗 Groups', reply_markup=keyboards.groups())
        return
    await message.answer(msg, reply_markup=keyboards.back())


@dispatcher.callback_query_handler(CallbackData('list'), state=Scrape.groups)
async def on_groups_list(callback: CallbackQuery, state: FSMContext):
    await Scrape.groups_list.set()
    groups = await Group.all()
    async with state.proxy() as user_data:
        user_data['list_page'] = 1
    await callback.message.edit_text('🗂 Groups', reply_markup=keyboards.groups_list(groups))
    await callback.answer()


@dispatcher.callback_query_handler(Regexp(r'page_\d+'), state=Scrape.groups_list)
async def on_groups_list_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split('_')[1])
    async with state.proxy() as user_data:
        old_page = user_data['list_page']
        if old_page != page:
            user_data['page'] = page
            groups = await Group.all()
            await callback.message.edit_reply_markup(reply_markup=keyboards.groups_list(groups, page))
        await callback.answer()


@dispatcher.callback_query_handler(Regexp(r'\d+'), state=Scrape.groups_list)
async def on_group_detail(callback: CallbackQuery, state: FSMContext):
    id = int(callback.data)
    try:
        group = await Group.get(id=id)
    except DoesNotExist:
        await callback.message.delete()
    else:
        await Scrape.group_detail.set()
        await state.update_data({'detail_id': id})
        await callback.message.edit_text(group.detail_msg, reply_markup=keyboards.group_detail(group))
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('status'), state=Scrape.group_detail)
async def on_group_status(callback: CallbackQuery, state: FSMContext):
    id = (await state.get_data())['detail_id']
    try:
        group = await Group.get(id=id)
    except DoesNotExist:
        await callback.message.delete()
    else:
        group.enabled = not group.enabled
        await group.save()
        await callback.message.edit_reply_markup(reply_markup=keyboards.group_detail(group))
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('group_to'), state=Scrape.group_detail)
async def on_group_set_target(callback: CallbackQuery, state: FSMContext):
    id = (await state.get_data())['detail_id']
    try:
        group = await Group.get(id=id)
    except DoesNotExist:
        await callback.message.delete()
        await callback.answer()
    else:
        if not group.is_target:
            await Group.all().update(is_target=False)
            group.is_target = True
            await group.save()
            await callback.message.edit_text(group.detail_msg, reply_markup=keyboards.group_detail(group))
        await callback.answer('Ok!')


@dispatcher.callback_query_handler(CallbackData('delete'), state=Scrape.group_detail)
async def on_group_delete(callback: CallbackQuery, state: FSMContext):
    id = (await state.get_data())['detail_id']
    try:
        group = await Group.get(id=id)
    except DoesNotExist:
        pass
    else:
        await group.delete()
    await Scrape.groups_list.set()
    async with state.proxy() as user_data:
        page = user_data['list_page']
    groups = await Group.all()
    await callback.message.edit_text('🗂 Groups', reply_markup=keyboards.groups_list(groups, page))
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('back'), state=(Scrape.add_group, Scrape.groups_list))
async def on_back_to_groups(callback: CallbackQuery, state: FSMContext):
    await Scrape.groups.set()
    await callback.message.edit_text('🔗 Groups', reply_markup=keyboards.groups())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('back'), state=Scrape.group_detail)
async def on_group_detail_back(callback: CallbackQuery, state: FSMContext):
    await Scrape.groups_list.set()
    page = (await state.get_data())['list_page']
    groups = await Group.all()
    await callback.message.edit_text('🗂 Groups', reply_markup=keyboards.groups_list(groups, page))


@dispatcher.callback_query_handler(CallbackData('start'), state=Scrape.main)
async def on_start_run(callback: CallbackQuery, state: FSMContext):
    message = callback.message
    chat_id = message.chat.id
    if task_running(chat_id):
        await Scrape.task_running.set()
        await message.edit_text('<b>Another task is running.</b>', reply_markup=keyboards.task_already_running())
        await callback.answer()
        return
    await callback.message.delete()
    if not await Account.exists():
        msg = '🚫 There are no accounts. Please add at least one to start run.'
    elif not await Group.filter(enabled=True, is_target=False).exists():
        msg = '🚫 There are no enabled source groups. Please add at least one to start run.'
    elif not await Group.filter(is_target=True).exists():
        msg = '🚫 Target group is not set. Please add it in the groups menu.'
    else:
        await callback.message.answer('Updating accounts...')
        await update_accounts_limits()
        if not await Account.filter(invites_sent__lt=F('invites_max')).exists():
            next_acc = await Account.filter(invites_reset_at__not_isnull=True).order_by('invites_reset_at').first()
            msg = '🙅🏻 All accounts have reached their limits.'
            if next_acc:
                date_str = next_acc.invites_reset_at.strftime('%d-%m-%Y %H:%M')
                msg += ' Next account will be available at {}'.format(date_str)
        else:
            await state.reset_state()
            queue = Queue()
            await state.set_data({'queue': queue})
            asyncio.create_task(tasks.scrape(chat_id, queue), name=str(chat_id))
            await callback.answer('420!')
            return
    await callback.message.answer(msg)
    await callback.message.answer('💥 Scrape', reply_markup=keyboards.scrape_menu())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('back'), state=Scrape.groups)
async def on_back_to_scrape(callback: CallbackQuery, state: FSMContext):
    await Scrape.main.set()
    await callback.message.edit_text('💥 Scrape', reply_markup=keyboards.scrape_menu())
    await callback.answer()

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
#     await message.edit_text('<b>There is no enabled run at the moment.</b>', reply_markup=None)
#     await callback.answer()
#     await to_main_menu(message)


@dispatcher.message_handler(commands=['stop'], state='*')
async def on_stop(message: Message, state: FSMContext):
    cancelled = False
    for task in asyncio.all_tasks():
        if task.get_name() == str(message.chat.id):
            task.cancel()
            cancelled = True
    if not cancelled:
        await message.answer('There is no enabled task at the moment.')
        await to_main_menu(message)
    else:
        await state.reset_state()


# @dispatcher.message_handler(state=Scrape.target_group_link)
# async def on_target_group_link(message: Message, state: FSMContext):
#     link = message.text.strip()
#     parts = urlsplit(link)
#     if not parts.scheme:
#         link = 'https://' + link
#     if not validators.url(link):
#         await message.answer('🚫 Entered URL is not valid. Please try again.')
#     else:
#         await state.reset_state(with_data=False)
#         queue = (await state.get_data())['queue']
#         queue.put_nowait(link)
#         await queue.join()


@dispatcher.message_handler(state=Scrape.add_limit)
@dispatcher.callback_query_handler(Regexp(r'^\d+$'), state=Scrape.add_limit)
async def on_scrape_add_limit(update, state: FSMContext):
    if type(update) == CallbackQuery:
        val = int(update.data)
    else:
        try:
            val = int(update.text.strip())
        except ValueError:
            await update.answer('🚫 Incorrect value. Please enter a number.')
            return
        val = max(1, val)
    await state.reset_state(with_data=False)
    queue = (await state.get_data())['queue']
    queue.put_nowait(val)


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


# @dispatcher.callback_query_handler(Regexp(r'\d+'), state=Scrape.select_group)
# async def select_group(callback: CallbackQuery, state: FSMContext):
#     await state.reset_state(with_data=False)
#     val = callback.tracker
#     await callback.message.delete()
#     # queue = (await state.get_data())['queue']
#     async with state.proxy() as user_data:
#         queue = user_data['queue']
#         try:
#             del user_data['groups']
#             del user_data['list_page']
#         except KeyError:
#             queue.get_nowait()
#             queue.task_done()
#     queue.put_nowait(val)
#     await callback.answer()
#     await queue.join()
#
# # TODO: Add handler for groups pagination
#
#
# @dispatcher.callback_query_handler(Regexp(r'^page_\d+$'), state=Scrape.select_group)
# async def select_group_page(callback: CallbackQuery, state: FSMContext):
#     page = int(callback.tracker.split('_')[1])
#     async with state.proxy() as user_data:
#         try:
#             old_page = user_data['list_page']
#         except KeyError:
#             old_page = 1
#         if page != old_page:
#             if 'groups' not in user_data:
#                 queue = user_data['queue']
#                 groups = queue.get_nowait()
#                 queue.task_done()
#                 user_data['groups'] = groups
#             else:
#                 groups = user_data['groups']
#             user_data['list_page'] = page
#             reply_markup = keyboards.groups_list(groups, page)
#             await callback.message.edit_reply_markup(reply_markup)
#     await callback.answer()
#
#
# @dispatcher.callback_query_handler(Regexp(r'\d+'), state=Scrape.select_multiple_groups)
# async def select_multiple_groups(callback: CallbackQuery, state: FSMContext):
#     val = callback.tracker
#     async with state.proxy() as user_data:
#         if 'groups' not in user_data:
#             queue = user_data['queue']
#             groups = queue.get_nowait()
#             queue.task_done()
#             user_data['groups'] = groups
#             page = 1
#             user_data['list_page'] = page
#             selected = []
#         else:
#             groups = user_data['groups']
#             selected = user_data['selected_groups']
#             page = user_data['list_page']
#         if val in selected:
#             selected.remove(val)
#         else:
#             selected.append(callback.tracker)
#         user_data['selected_groups'] = selected
#     reply_markup = keyboards.multiple_groups(groups, selected, page)
#     await callback.message.edit_reply_markup(reply_markup)
#     await callback.answer()
#
#
# @dispatcher.callback_query_handler(Regexp(r'^page_\d+$'), state=Scrape.select_multiple_groups)
# async def select_multiple_groups_page(callback: CallbackQuery, state: FSMContext):
#     page = int(callback.tracker.split('_')[1])
#     async with state.proxy() as user_data:
#         try:
#             groups = user_data['groups']
#         except KeyError:
#             queue = user_data['queue']
#             groups = queue.get_nowait()
#             queue.task_done()
#             user_data['groups'] = groups
#             selected = []
#             old_page = 1
#         else:
#             selected = user_data['selected_groups']
#             old_page = user_data['list_page']
#         if old_page != page:
#             user_data['list_page'] = page
#             reply_markup = keyboards.multiple_groups(groups, selected, page)
#             await callback.message.edit_reply_markup(reply_markup)
#     await callback.answer()
#
#
# @dispatcher.callback_query_handler(CallbackData('done'), state=Scrape.select_multiple_groups)
# async def select_multiple_groups_done(callback: CallbackQuery, state: FSMContext):
#     async with state.proxy() as user_data:
#         try:
#             selected = user_data['selected_groups']
#         except KeyError:
#             selected = None
#         if selected:
#             await state.reset_state(with_data=False)
#             await callback.message.delete()
#             queue = user_data['queue']
#             queue.put_nowait(selected)
#             msg = ''
#         else:
#             msg = 'Please select at least one group.'
#     await callback.answer(msg)


@dispatcher.callback_query_handler(CallbackData('blank'), state='*')
async def do_nothing(callback: CallbackQuery):
    await callback.answer()
