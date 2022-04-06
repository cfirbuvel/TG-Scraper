import asyncio
import datetime
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
from aiogram.dispatcher.filters import ContentTypeFilter, Regexp, Text
from aiogram.types import Message, CallbackQuery
from aiogram.types.message import ContentType
from telethon import TelegramClient
from telethon.errors import ApiIdInvalidError, PhoneNumberInvalidError
from telethon.sessions import MemorySession
from tortoise.expressions import F
from tortoise.exceptions import DoesNotExist
import validators

from . import tasks, keyboards, states
from .bot import dispatcher
from .filters import CallbackData
from .models import Account, Group, Settings, ApiConfig
from .utils import task_running, session_db_to_string


logger = logging.getLogger(__name__)


async def to_main_menu(message, callback_query=None, callback_answer=None, edit=False):
    await states.Menu.main.set()
    params = {'text': 'Main', 'reply_markup': keyboards.main_menu()}
    if edit:
        await message.edit_text(**params)
    else:
        await message.answer(**params)
    if callback_query:
        await callback_query.answer(text=callback_answer)

async def enter_settings(update):
    await states.Settings.main.set()
    settings = await Settings.get()
    msg = str(settings)
    reply_markup = await keyboards.settings_menu()
    if type(update) == Message:
        await update.answer(msg, reply_markup=reply_markup)
    else:
        await update.message.edit_text(msg, reply_markup=reply_markup)
        await update.answer()

@dispatcher.message_handler(commands=['start'], state='*')
async def start(message: Message):
    await to_main_menu(message)


@dispatcher.callback_query_handler(CallbackData('add_acc'), state=(states.Menu.main, None))
async def add_acc(callback: CallbackQuery, state: FSMContext):
    await states.AddAccount.phone.set()
    await callback.message.edit_text('Please enter phone number', reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(state=states.AddAccount.phone)
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
        await states.AddAccount.api_id.set()
        await message.answer('Please enter <b>API ID</b>', reply_markup=keyboards.cancel_back())
        return
    await message.answer('Please enter phone number', reply_markup=keyboards.back())


@dispatcher.callback_query_handler(CallbackData('back'), state=states.AddAccount.phone)
async def add_user_enter_phone_back(callback_query: CallbackQuery, state: FSMContext):
    await state.reset_data()
    await to_main_menu(callback_query.message, callback_query=callback_query, edit=True)


@dispatcher.message_handler(state=states.AddAccount.api_id)
async def add_user_enter_id(message: Message, state: FSMContext):
    api_id = message.text
    reply_markup = keyboards.cancel_back()
    if not api_id.isdigit():
        await message.answer('Please enter <b>API ID</b>\n<i>It should be a number</i>', reply_markup=reply_markup)
        return
    async with state.proxy() as user_data:
        user_data['add_user']['api_id'] = api_id
    await states.AddAccount.api_hash.set()
    await message.answer('Please enter <b>API hash</b>', reply_markup=reply_markup)


@dispatcher.callback_query_handler(CallbackData('back'), state=states.AddAccount.api_id)
async def add_user_enter_id_back(callback_query: CallbackQuery, state: FSMContext):
    await states.AddAccount.phone.set()
    await callback_query.message.edit_text('Please enter phone number', reply_markup=keyboards.back())
    await callback_query.answer()


@dispatcher.message_handler(state=states.AddAccount.api_hash)
async def add_user_enter_hash(message: Message, state: FSMContext):
    async with state.proxy() as user_data:
        user_data['add_user']['api_hash'] = message.text.strip()
    await states.AddAccount.name.set()
    await message.answer('Please enter account name', reply_markup=keyboards.cancel_back())


@dispatcher.callback_query_handler(CallbackData('back'), state=states.AddAccount.api_hash)
async def add_user_enter_hash_back(callback_query: CallbackQuery, state: FSMContext):
    await states.AddAccount.api_id.set()
    await callback_query.message.edit_text('Please enter *API ID*', reply_markup=keyboards.cancel_back())
    await callback_query.answer()


@dispatcher.message_handler(state=states.AddAccount.name)
async def add_user_enter_name(message: Message, state: FSMContext):
    async with state.proxy() as user_data:
        data = user_data['add_user']
        settings = await Settings.get()
        data['invites_max'] = settings.get_relative_invite_limit()
        await Account.create(name=message.text, **data)
    await message.answer(r'<i>Account has been created.</i>')
    await to_main_menu(message)


@dispatcher.callback_query_handler(CallbackData('back'), state=states.AddAccount.name)
async def add_user_enter_name_back(callback_query: CallbackQuery, state: FSMContext):
    await states.AddAccount.api_hash.set()
    await callback_query.message.edit_text('Please enter <b>API hash</b>', reply_markup=keyboards.cancel_back())
    await callback_query.answer()


@dispatcher.callback_query_handler(CallbackData('to_menu'), state=(
        states.AddAccount.api_id, states.AddAccount.api_hash, states.AddAccount.name,
        states.Accounts.list, states.Settings.main, states.Groups.main
))
async def on_back_to_menu(callback_query: CallbackQuery, state: FSMContext):
    await state.reset_data()
    await to_main_menu(callback_query.message, callback_query=callback_query, edit=True)


@dispatcher.callback_query_handler(CallbackData('accounts'), state=(states.Menu.main, None))
async def accounts_menu(callback_query: CallbackQuery, state: FSMContext):
    await states.Accounts.list.set()
    accounts = await Account.all().values_list('id', 'name')
    await state.set_data({'list_page': 1})
    await callback_query.message.edit_text('Accounts', reply_markup=keyboards.accounts_list(accounts))
    await callback_query.answer()


@dispatcher.callback_query_handler(Regexp(r'^page_\d+$'), state=states.Accounts.list)
async def accounts_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split('_')[1])
    async with state.proxy() as user_data:
        old_page = user_data['list_page']
        if page != old_page:
            user_data['list_page'] = page
            accounts = await Account.all().values_list('id', 'name')
            await callback.message.edit_text('Accounts', reply_markup=keyboards.accounts_list(accounts, page))
    await callback.answer()


@dispatcher.callback_query_handler(Regexp(r'^\d+$'), state=states.Accounts.list)
async def accounts_select(callback: CallbackQuery, state: FSMContext):
    await states.Accounts.detail.set()
    acc = await Account.get(id=int(callback.data))
    await state.update_data({'acc_id': acc.id})
    await callback.message.edit_text(acc.get_detail_msg(), reply_markup=keyboards.account_detail())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('delete'), state=states.Accounts.detail)
async def account_delete(callback: CallbackQuery, state: FSMContext):
    await states.Accounts.delete.set()
    user_data = await state.get_data()
    acc = await Account.get(id=user_data['acc_id'])
    msg = 'Delete account <b>{}</b>?'.format(acc.safe_name)
    await callback.message.edit_text(msg, reply_markup=keyboards.yes_no())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('yes'), state=states.Accounts.delete)
async def account_delete_yes(callback: CallbackQuery, state: FSMContext):
    await states.Accounts.list.set()
    async with state.proxy() as user_data:
        acc_id = user_data['acc_id']
        del user_data['acc_id']
        page = user_data['list_page']
    acc = await Account.get(id=acc_id)
    await acc.delete()
    accounts = await Account.all().values_list('id', 'name')
    await callback.message.edit_text('Accounts', reply_markup=keyboards.accounts_list(accounts, page))
    await callback.answer('Deleted')


@dispatcher.callback_query_handler(CallbackData('no'), state=states.Accounts.delete)
async def account_delete_no(callback: CallbackQuery, state: FSMContext):
    await states.Accounts.detail.set()
    user_data = await state.get_data()
    acc = await Account.get(id=user_data['acc_id'])
    await callback.message.edit_text(acc.get_detail_msg(), reply_markup=keyboards.account_detail())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('set_main'), state=states.Accounts.detail)
async def on_account_set_main(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    acc = await Account.get(id=user_data['acc_id'])
    if not acc.master:
        await Account.filter(master=True).update(master=False)
        acc.master = True
        await acc.save()
        await callback.message.edit_text(acc.get_detail_msg(), reply_markup=keyboards.account_detail())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('back'), state=states.Accounts.detail)
async def account_detail_back(callback: CallbackQuery, state: FSMContext):
    await states.Accounts.list.set()
    page = (await state.get_data())['list_page']
    accounts = await Account.all().values_list('id', 'name')
    await callback.message.edit_text('Accounts', reply_markup=keyboards.accounts_list(accounts, page))
    await callback.answer()


@dispatcher.callback_query_handler(Text('groups'), state=states.Menu.main)
async def on_groups(callback: CallbackQuery, state: FSMContext):
    await states.Groups.main.set()
    await callback.message.edit_text('🔗 Groups', reply_markup=keyboards.groups())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('add'), state=states.Groups.main)
async def on_add_group(callback: CallbackQuery, state: FSMContext):
    await states.Groups.add.set()
    await callback.message.edit_text('Please enter group invite link.', reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(state=states.Groups.add)
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
        await states.Groups.main.set()
        await message.answer('✔️ Added group.')
        await message.answer('🔗 Groups', reply_markup=keyboards.groups())
        return
    await message.answer(msg, reply_markup=keyboards.back())


@dispatcher.callback_query_handler(CallbackData('list'), state=states.Groups.main)
async def on_groups_list(callback: CallbackQuery, state: FSMContext):
    await states.Groups.list.set()
    groups = await Group.all()
    async with state.proxy() as user_data:
        user_data['list_page'] = 1
    await callback.message.edit_text('🗂 Groups', reply_markup=keyboards.groups_list(groups))
    await callback.answer()


@dispatcher.callback_query_handler(Regexp(r'page_\d+'), state=states.Groups.list)
async def on_groups_list_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split('_')[1])
    async with state.proxy() as user_data:
        old_page = user_data['list_page']
        if old_page != page:
            user_data['page'] = page
            groups = await Group.all()
            await callback.message.edit_reply_markup(reply_markup=keyboards.groups_list(groups, page))
        await callback.answer()


@dispatcher.callback_query_handler(Regexp(r'\d+'), state=states.Groups.list)
async def on_group_detail(callback: CallbackQuery, state: FSMContext):
    id = int(callback.data)
    try:
        group = await Group.get(id=id)
    except DoesNotExist:
        await callback.message.delete()
    else:
        await states.Groups.detail.set()
        await state.update_data({'detail_id': id})
        await callback.message.edit_text(group.detail_msg, reply_markup=keyboards.group_detail(group))
    await callback.answer()


@dispatcher.callback_query_handler(Text('status'), state=states.Groups.detail)
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


@dispatcher.callback_query_handler(Text('group_to'), state=states.Groups.detail)
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


@dispatcher.callback_query_handler(Text('delete'), state=states.Groups.detail)
async def on_group_delete(callback: CallbackQuery, state: FSMContext):
    id = (await state.get_data())['detail_id']
    try:
        group = await Group.get(id=id)
    except DoesNotExist:
        pass
    else:
        await group.delete()
    await states.Groups.list.set()
    async with state.proxy() as user_data:
        page = user_data['list_page']
    groups = await Group.all()
    await callback.message.edit_text('🗂 Groups', reply_markup=keyboards.groups_list(groups, page))
    await callback.answer()


@dispatcher.callback_query_handler(Text(['settings_menu', 'back']), state=(
        states.Menu.main, states.ApiConf.main, states.Settings.invites_limit,
        states.Settings.limit_reset, states.Settings.last_seen, states.Settings.join_delay,
        states.Settings.add_sessions, states.Scrape.main,  None
))
async def on_settings(callback: CallbackQuery, state: FSMContext):
    await enter_settings(callback)


@dispatcher.callback_query_handler(Text(['api_configs', 'back', 'cancel']), state=(
        states.Settings.main, states.ApiConf.enter_id, states.ApiConf.enter_hash,
        states.ApiConf.detail
))
async def on_api_configs(callback: CallbackQuery, state: FSMContext):
    await states.ApiConf.main.set()
    await state.update_data({'list_page': 1})
    msg = 'Add api id and hash pairs.\nThey will be split equally across sessions.'
    confs = await ApiConfig.all()
    reply_markup = keyboards.api_configs(confs)
    await callback.message.edit_text(msg, reply_markup=reply_markup)
    await callback.answer()


@dispatcher.callback_query_handler(Regexp(r'page_\d+'), state=states.ApiConf.main)
async def on_api_configs_page(callback: CallbackQuery, state: FSMContext):
    await states.ApiConf.main.set()
    page = int(callback.data.split('_')[1])
    await state.update_data({'list_page': page})
    confs = await ApiConfig.all()
    reply_markup = keyboards.api_configs(confs, page=page)
    await callback.message.edit_reply_markup(reply_markup=reply_markup)
    await callback.answer()


@dispatcher.callback_query_handler(Text('add'), state=states.ApiConf.main)
async def on_add_api_config(callback: CallbackQuery, state: FSMContext):
    await states.ApiConf.enter_id.set()
    msg = 'Please enter Api id.'
    await callback.message.edit_text(msg, reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(state=states.ApiConf.enter_id)
async def on_api_config_enter_id(message: Message, state: FSMContext):
    try:
        api_id = int(message.text.replace(' ', ''))
    except KeyError:
        msg = '🚫 Invalid Api id. Please enter a number.'
        await message.reply(msg, reply_markup=keyboards.back())
    else:
        await states.ApiConf.enter_hash.set()
        await state.update_data({'api_config_id': api_id})
        await message.answer('Please enter Api hash.', reply_markup=keyboards.cancel_back())


@dispatcher.message_handler(state=states.ApiConf.enter_hash)
async def on_api_config_enter_hash(message: Message, state: FSMContext):
    await states.ApiConf.detail.set()
    api_hash = message.text.replace(' ', '')
    user_data = await state.get_data()
    api_id = user_data['api_config_id']
    try:
        conf = await ApiConfig.get(api_id=api_id, hash=api_hash)
        await message.reply('Api config already exists.')
    except DoesNotExist:
        conf = await ApiConfig.create(api_id=api_id, hash=api_hash)
    await state.update_data({'api_config': conf.id})
    await message.answer(str(conf), reply_markup=keyboards.api_config_detail())


@dispatcher.callback_query_handler(Text('step_back'), state=states.ApiConf.enter_hash)
async def on_api_config_enter_hash_back(callback: CallbackQuery, state: FSMContext):
    await states.ApiConf.enter_hash.set()
    await callback.message.edit_text('Please enter Api id.', reply_markup=keyboards.back())


@dispatcher.callback_query_handler(Regexp(r'\d+'), state=states.ApiConf.main)
async def on_api_config_select(callback: CallbackQuery, state: FSMContext):
    await states.ApiConf.detail.set()
    conf = await ApiConfig.get(id=int(callback.data))
    await state.update_data({'api_config': conf.id})
    await callback.message.edit_text(str(conf), reply_markup=keyboards.api_config_detail())
    await callback.answer()


@dispatcher.callback_query_handler(Text('verify'), state=states.ApiConf.detail)
async def on_api_config_verify(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    conf = await ApiConfig.get(id=user_data['api_config'])
    verified = True
    msg = 'Verified.'
    client = TelegramClient(MemorySession(), conf.api_id, conf.hash)
    await client.connect()
    try:
        await client.send_code_request('+7000000000')
    except ApiIdInvalidError:
        verified = False
        msg = 'Api id/api hash combination is not valid.'
    except PhoneNumberInvalidError:
        pass
    await client.disconnect()
    if conf.active != verified:
        conf.active = verified
        await conf.save()
        await callback.message.edit_text(str(conf), reply_markup=keyboards.api_config_detail())
    await callback.answer(msg)


@dispatcher.callback_query_handler(Text('delete'), state=states.ApiConf.detail)
async def on_api_config_delete(callback: CallbackQuery, state: FSMContext):
    await states.ApiConf.delete.set()
    await callback.message.edit_text('Are you sure?', reply_markup=keyboards.yes_no())
    await callback.answer()


@dispatcher.callback_query_handler(Text(['yes', 'no']), state=states.ApiConf.delete)
async def on_api_config_delete_confirm(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    conf = await ApiConfig.get(id=user_data['api_config'])
    if callback.data == 'yes':
        await states.ApiConf.main.set()
        await conf.delete()
        try:
            page = user_data['list_page']
        except KeyError:
            page = 1
        confs = await ApiConfig.all()
        msg = 'Add api id and hash pairs.\nThey will be split equally across sessions.'
        reply_markup = keyboards.api_configs(confs, page)
        await callback.message.edit_text(msg, reply_markup=reply_markup)
        await callback.answer('Config has been deleted.')
    else:
        await callback.message.edit_text(str(conf), reply_markup=keyboards.api_config_detail())
        await callback.answer()


@dispatcher.callback_query_handler(CallbackData('invites'), state=states.Settings.main)
async def on_invites_limit(callback: CallbackQuery, state: FSMContext):
    await states.Settings.invites_limit.set()
    settings = await Settings.get()
    msg = ('Current limit: <b>{}</b>\n'
           'Enter number of users one account can invite (50 max).\n'
           '+-5 value will be set to accounts.').format(settings.invites_limit)
    await callback.message.edit_text(msg, reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(state=states.Settings.invites_limit)
async def on_invites_limit_set(message: Message, state: FSMContext):
    try:
        limit = int(message.text.strip())
    except ValueError:
        msg = '🚫 Invalid value. Please enter a number.'
        await message.reply(msg, reply_markup=keyboards.back())
    else:
        limit = min(50, abs(limit))
        settings = await Settings.get()
        if limit != settings.invites_limit:
            settings.invites_limit = limit
            await settings.save()
            await message.reply('Updating accounts with new limits.')
            for acc in await Account.all():
                acc.invites_max = settings.get_relative_invite_limit()
                await acc.save()
        await enter_settings(message)


@dispatcher.callback_query_handler(Text('reset'), state=states.Settings.main)
async def on_invites_reset(callback: CallbackQuery, state: FSMContext):
    await states.Settings.limit_reset.set()
    settings = await Settings.get()
    msg = ('Enter number of days passed before resetting limit (between 1 and 180).\n'
           '<i>Current number: {}</i>').format(settings.invites_timeframe)
    await callback.message.edit_text(msg, reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(state=states.Settings.limit_reset)
async def on_invites_reset_set(message: Message, state: FSMContext):
    try:
        value = int(message.text.strip())
    except ValueError:
        msg = '🚫 Invalid value. Please enter a number.'
        await message.reply(msg, reply_markup=keyboards.back())
    else:
        value = min(abs(value), 180)
        settings = await Settings.get()
        settings.invites_timeframe = value
        await settings.save()
        await enter_settings(message)

# @dispatcher.callback_query_handler(CallbackData('skip_sign_in'), state=Settings.run)
# async def on_skip_sign_in_toggle(callback: CallbackQuery, state: FSMContext):
#     settings.skip_sign_in = not settings.skip_sign_in
#     await callback.message.edit_reply_markup(reply_markup=keyboards.run_settings())
#     await callback.answer()


@dispatcher.callback_query_handler(Text('last_seen'), state=states.Settings.main)
async def on_last_seen_filter(callback: CallbackQuery, state: FSMContext):
    await states.Settings.last_seen.set()
    msg = 'Select a last seen status to filter users by'
    settings = await Settings.get()
    await callback.message.edit_text(msg, reply_markup=keyboards.last_seen_filter(settings))
    await callback.answer()


@dispatcher.callback_query_handler(Regexp(r'^\d+$'), state=states.Settings.last_seen)
async def on_last_seen_filter_set(callback: CallbackQuery, state: FSMContext):
    choice = int(callback.data)
    settings = await Settings.get()
    if settings.last_seen != choice:
        settings.last_seen = choice
        await settings.save()
        msg = 'Select a last seen status to filter users by'
        await callback.message.edit_text(msg, reply_markup=keyboards.last_seen_filter(settings))
    await callback.answer()


@dispatcher.callback_query_handler(Text('group_join_interval'), state=states.Settings.main)
async def on_join_delay(callback: CallbackQuery, state: FSMContext):
    await states.Settings.join_delay.set()
    settings = await Settings.get()
    msg = ('Enter interval for joining a group in seconds.\n'
           '<i>(Small random offset will be added)</i>\n\n'
           'Current value: <b>{}</b> seconds.').format(settings.group_join_interval)
    await callback.message.edit_text(msg, reply_markup=keyboards.back())
    await callback.answer()


@dispatcher.message_handler(state=states.Settings.join_delay)
async def on_join_delay_set(message: Message, state: FSMContext):
    try:
        value = int(message.text.strip())
    except ValueError:
        msg = '🚫 Invalid value. Please enter a number.'
        await message.reply(msg, reply_markup=keyboards.back())
    else:
        settings = await Settings.get()
        settings.group_join_interval = value
        await settings.save()
        await enter_settings(message)


@dispatcher.callback_query_handler(Text('proxy_toggle'), state=states.Settings.main)
async def on_proxy_toggle(callback: CallbackQuery, state: FSMContext):
    # TODO: add proxy list in menu, add verifying that proxies exist
    settings = await Settings.get()
    settings.enable_proxy = not settings.enable_proxy
    await settings.save()
    await enter_settings(callback)

@dispatcher.callback_query_handler(Text('add_sessions'), state=states.Settings.main)
async def add_sessions(callback: CallbackQuery, state: FSMContext):
    if not await ApiConfig.exists():
        await callback.answer('🚫 Please add at least one api config.')
        return
    await states.Settings.add_sessions.set()
    msg = 'Please upload <b>.zip</b> archive with session files or <b>.session</b> file.'
    await callback.message.edit_text(msg, reply_markup=keyboards.back())
    await callback.answer()


# TODO: seems that file sessions are not cleared
@dispatcher.message_handler(content_types=ContentType.DOCUMENT, state=states.Settings.add_sessions)
async def add_sessions_upload(message: Message, state: FSMContext):
    document = message.document
    phone, ext = os.path.splitext(document.file_name)
    if ext in ('.zip', '.session'):
        sessions = {}
        dirname = 'temp/{}'.format(message.chat.id)
        if os.path.isdir(dirname):
            shutil.rmtree(dirname)
        os.makedirs(dirname, exist_ok=True)
        if ext == '.zip':
            file = io.BytesIO()
            await message.document.download(destination_file=file)
            try:
                archive = zipfile.ZipFile(file)
            except zipfile.BadZipfile:
                await states.Settings.add_sessions.set()
                msg = '🚫 Invalid file.\nPlease upload solid <b>.zip</b> archive.'
                await message.reply(msg, reply_markup=keyboards.back())
                return
            message = await message.answer('Creating accounts from sessions')
            task = asyncio.create_task(tasks.show_loading(message))
            archive.extractall(path=dirname)
            for dirpath, dirnames, filenames in os.walk(dirname):
                for filename in filenames:
                    phone, ext = os.path.splitext(filename)
                    if ext == '.session':
                        sessions[phone] = await session_db_to_string(os.path.join(dirpath, filename))
            task.cancel()
        elif ext == '.session':
            if await Account.filter(phone=phone).exists():
                msg = '🚫 This account already exists. Please upload another file.'
                await message.reply(msg, reply_markup=keyboards.back())
                return
            else:
                file_path = os.path.join(dirname, document.file_name)
                await document.download(destination_file=file_path)
                sessions[phone] = await session_db_to_string(file_path)
        confs = await ApiConfig.all().values_list('api_id', 'hash')
        if len(sessions) > 1:
            random.shuffle(confs)
            await message.delete()
        settings = await Settings.get_cached()
        created = 0
        exist = 0
        confs_len = len(confs)
        for i, data in enumerate(sessions.items()):
            phone, session = data
            api_id, api_hash = confs[i % confs_len]
            if not await Account.filter(phone=phone).exists():
                await Account.create(
                    api_id=api_id,
                    api_hash=api_hash,
                    name=phone,
                    phone=phone,
                    session_string=session,
                    invites=settings.get_invites_random(),
                )
                created += 1
            else:
                exist += 1
        msg = '{} accounts has been created.'.format(created)
        if exist:
            msg += '\n<i>{} accounts already exist.</i>'.format(exist)
        await message.answer(msg)
        shutil.rmtree(dirname)
        await enter_settings(message)
    else:
        msg = '🚫 Unsupported file format. Valid are: <b>.session</b>, <b>.zip</b>.'
        await message.reply(msg, reply_markup=keyboards.back())


# @dispatcher.callback_query_handler(Text('back'), state=Settings.add_sessions)
# async def on_back_to_settings():
#     pass


@dispatcher.callback_query_handler(Text('scrape'), state=(states.Menu.main, None))
async def on_scrape(callback: CallbackQuery, state: FSMContext):
    await states.Scrape.main.set()
    await callback.message.edit_text('💥 Scrape', reply_markup=keyboards.scrape_menu())
    await callback.answer()


@dispatcher.callback_query_handler(Text('back'), state=(states.Groups.add, states.Groups.list))
async def on_back_to_groups(callback: CallbackQuery, state: FSMContext):
    await states.Groups.main.set()
    await callback.message.edit_text('🔗 Groups', reply_markup=keyboards.groups())
    await callback.answer()


@dispatcher.callback_query_handler(CallbackData('back'), state=states.Groups.detail)
async def on_group_detail_back(callback: CallbackQuery, state: FSMContext):
    await states.Groups.list.set()
    page = (await state.get_data())['list_page']
    groups = await Group.all()
    await callback.message.edit_text('🗂 Groups', reply_markup=keyboards.groups_list(groups, page))


@dispatcher.callback_query_handler(CallbackData('start'), state=states.Scrape.main)
async def on_start_run(callback: CallbackQuery, state: FSMContext):
    message = callback.message
    chat_id = message.chat.id
    if task_running(chat_id):
        await states.Scrape.task_running.set()
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
        await Account.update_invites()
        if not await Account.filter(authenticated=True, deactivated=False, invites__gt=0).exists():
            msg = '🙅🏻 All operating accounts have reached their limits.'
        else:
            await state.reset_state()
            # queue = Queue()
            # await state.set_data({'queue': queue})
            asyncio.create_task(tasks.scrape(chat_id), name=str(chat_id))
            await callback.answer('420!')
            return
    await callback.message.answer(msg)
    await callback.message.answer('💥 Scrape', reply_markup=keyboards.scrape_menu())
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


@dispatcher.message_handler(state=states.Scrape.add_limit)
@dispatcher.callback_query_handler(Regexp(r'^\d+$'), state=states.Scrape.add_limit)
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


@dispatcher.message_handler(Regexp(r'^[A-Za-z0-9_ ]+$'), state=states.Scrape.enter_code)
@dispatcher.callback_query_handler(CallbackData('resend', 'skip'), state=states.Scrape.enter_code)
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


@dispatcher.callback_query_handler(CallbackData('blank'), state='*')
async def do_nothing(callback: CallbackQuery):
    await callback.answer()
