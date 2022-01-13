import functools
import math
import operator

from aiogram.types.inline_keyboard import InlineKeyboardButton, InlineKeyboardMarkup

from .conf import LastSeenEnum, Settings


PAGE_SIZE = 25


def inline_markup(func):

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        keyboard = []
        for row in func(*args, **kwargs):
            keyboard.append([InlineKeyboardButton(**data) for data in row])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    return wrapper


@inline_markup
def main_menu():
    return [
        [{'text': '🤖  Add account', 'callback_data': 'add_acc'}],
        [{'text': '🗂  Accounts', 'callback_data': 'accounts'}],
        [{'text': '⚙️  Settings', 'callback_data': 'settings_menu'}],
        [{'text': '💥  Start scrape', 'callback_data': 'start_scrape'}],
    ]


@inline_markup
def back():
    return [
        [{'text': '↩ Back', 'callback_data': 'back'}]
    ]


@inline_markup
def cancel_back():
    return [
        [{'text': '❌ Cancel', 'callback_data': 'to_menu'}, {'text': '↩ Back', 'callback_data': 'back'}],
    ]


@inline_markup
def yes_no():
    return [
        [{'text': '✖️ No', 'callback_data': 'no'}, {'text': '✔️ Yes', 'callback_data': 'yes'}]
    ]


# TODO: Limit code requests to avoid flood ban
@inline_markup
def code_request():
    return [
        [{'text': '🔁 Resend code', 'callback_data': 'resend'}],
        [{'text': '⏩ Skip', 'callback_data': 'skip'}],
    ]


def general_list(items, page):
    # if action:
    #     op = {'prev': operator.sub, 'next': operator.add}[action]
    #     page = op(page, 1)
    #     last_page = math.ceil(total_len / PAGE_SIZE)
    #     if page == 0:
    #         page = last_page
    #     elif page > last_page:
    #         page = 1
    total_len = len(items)
    start = (page - 1) * PAGE_SIZE
    end = page * PAGE_SIZE
    items = items[start:end]
    rows = [[{'text': name, 'callback_data': id}] for id, name in items]
    if len(items) < total_len:
        last_page = math.ceil(total_len / PAGE_SIZE)
        prev_page = page - 1 or last_page
        next_page = page + 1
        if next_page > last_page:
            next_page = 1
        rows.append([
            {'text': '⏪ Prev', 'callback_data': 'page_{}'.format(prev_page)},
            {'text': 'Page {}'.format(page), 'callback_data': 'blank'},
            {'text': '⏩ Next', 'callback_data': 'page_{}'.format(next_page)}
        ])
    return rows


@inline_markup
def accounts_list(items, page=1):
    rows = general_list(items, page)
    rows.append([{'text': '↩ Back', 'callback_data': 'to_menu'}])
    return rows


@inline_markup
def account_detail():
    return [
        [{'text': '🚫 Delete', 'callback_data': 'delete'}],
        [{'text': '🎩 Set as main', 'callback_data': 'set_main'}],
        [{'text': '↩ Back', 'callback_data': 'back'}]
    ]


@inline_markup
def settings_menu():
    return [
        [{'text': '🎛 Run', 'callback_data': 'run'}],
        [{'text': '🚷 Last seen filter', 'callback_data': 'last_seen_filter'}],
        [{'text': '⏱ Accounts invite delay', 'callback_data': 'join_delay'}],
        [{'text': '💾 Add sessions', 'callback_data': 'add_sessions'}],
        [{'text': '↩ Back', 'callback_data': 'to_menu'}]
    ]


@inline_markup
def run_settings():
    skip_sign_in = 'Skip sign in{}'.format(' ☑' if Settings().skip_sign_in else '')
    return [
        [{'text': '🎚 Invites limit', 'callback_data': 'invites'}],
        [{'text': '⌛ Limit reset', 'callback_data': 'reset'}],
        [{'text': skip_sign_in, 'callback_data': 'skip_sign_in'}],
        [{'text': '↩ Back', 'callback_data': 'back'}]
    ]


@inline_markup
def last_seen_filter():
    markup = []
    settings = Settings()
    for status in LastSeenEnum:
        text = status.verbose_name
        val = status.value
        if val == settings.last_seen_filter:
            text += '  💚'
        markup.append([{'text': text, 'callback_data': str(val)}])
    markup.append([{'text': '↩ Back', 'callback_data': 'settings_menu'}])
    return markup


@inline_markup
def start_scrape():
    return [
        [{'text': '▶ Run once', 'callback_data': 'once'}],
        [{'text': '🔁 Run every 24 hours', 'callback_data': 'repeatedly'}],
        [{'text': '↩ Back', 'callback_data': 'to_menu'}],
    ]


@inline_markup
def task_already_running():
    return [
        [{'text': '☠️Stop', 'callback_data': 'stop'}],
        [{'text': '↩ Back', 'callback_data': 'to_menu'}]
    ]


# @inline_markup
# def stop_run():
#     return [
#         [{'text': '☠️Stop Run', 'callback_data': 'stop_run'}],
#     ]


@inline_markup
def groups_list(items, page=1):
    rows = general_list(items, page)
    # rows.append([{'text': '☠️Stop Run', 'callback_data': 'stop_run'}])
    return rows


@inline_markup
def multiple_groups(items, selected=[], page=1):
    total_len = len(items)
    start = (page - 1) * PAGE_SIZE
    end = page * PAGE_SIZE
    items = items[start:end]
    rows = []
    for id, name in items:
        icon = '☑' if id in selected else '◻'
        rows.append([{'text': '{} {}'.format(name, icon), 'callback_data': id}])
    if len(items) < total_len:
        last_page = math.ceil(total_len / PAGE_SIZE)
        prev_page = page - 1 or last_page
        next_page = page + 1
        if next_page > last_page:
            next_page = 1
        rows.append([
            {'text': '⏪ Prev', 'callback_data': 'page_{}'.format(prev_page)},
            {'text': 'Page {}'.format(page), 'callback_data': 'blank'},
            {'text': '⏩ Next', 'callback_data': 'page_{}'.format(next_page)}
        ])
    rows.append([{'text': '✅ Done', 'callback_data': 'done'}])
    return rows
