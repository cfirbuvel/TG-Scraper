import functools
import math
import operator

from aiogram.types.inline_keyboard import InlineKeyboardButton, InlineKeyboardMarkup

from .models import Settings

PAGE_SIZE = 25


def inline_markup(func):

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        keyboard = []
        for row in func(*args, **kwargs):
            keyboard.append([InlineKeyboardButton(**data) for data in row])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    return wrapper

def async_inline_markup(func):

    async def wrapper(*args, **kwargs):
        keyboard = []
        for row in await func(*args, **kwargs):
            keyboard.append([InlineKeyboardButton(**data) for data in row])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    return wrapper


@inline_markup
def main_menu():
    return [
        [{'text': '🤖 Add account', 'callback_data': 'add_acc'}],
        [{'text': '🗂 Accounts', 'callback_data': 'accounts'}],
        [{'text': '🔗 Groups', 'callback_data': 'groups'}],
        [{'text': '⚙️ Settings', 'callback_data': 'settings_menu'}],
        [{'text': '💥 Scrape', 'callback_data': 'scrape'}],
    ]


@inline_markup
def back():
    return [
        [{'text': '↩ Back', 'callback_data': 'back'}]
    ]


@inline_markup
def cancel_back():
    return [
        [{'text': '❌ Cancel', 'callback_data': 'cancel'}, {'text': '↩ Back', 'callback_data': 'step_back'}],
    ]


@inline_markup
def yes_no():
    return [
        [{'text': '✔️ Yes', 'callback_data': 'yes'}, {'text': '✖️ No', 'callback_data': 'no'}]
    ]


# TODO: Limit code requests to avoid flood ban
@inline_markup
def code_request():
    return [
        [{'text': '🔁 Resend code', 'callback_data': 'resend'}],
        [{'text': '⏩ Skip', 'callback_data': 'skip'}],
    ]


def general_list(items, page):
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


@async_inline_markup
async def settings_menu():
    settings = await Settings.get_cached()
    recent = '⌚ Last seen recently' if settings.recent else '*️⃣ All users'
    proxy = '👤 Use proxy  {}'.format('☑' if settings.enable_proxy else '◻')
    return [
        # [{'text': '🎛 Run', 'callback_data': 'run'}],
        [{'text': '🆔 Api configs', 'callback_data': 'api_configs'}],
        [{'text': '⏱ Group join delay', 'callback_data': 'join_interval'}],
        # [{'text': '', 'callback_data': ''}]
        [{'text': '🎚 Account invites limit', 'callback_data': 'invites_limit'}],
        [{'text': '⌛ Account limit reset', 'callback_data': 'invites_reset'}],
        [{'text': recent, 'callback_data': 'recent_toggle'}],
        # [{'text': proxy, 'callback_data': 'proxy_toggle'}],
        [{'text': '💾 Add sessions', 'callback_data': 'add_sessions'}],
        [{'text': '↩ Back', 'callback_data': 'to_menu'}]
    ]


@inline_markup
def run_settings():
    # skip_sign_in = 'Skip sign in{}'.format(' ☑' if Settings().skip_sign_in else '')
    return [
        [{'text': '🎚 Invites limit', 'callback_data': 'invites'}],
        [{'text': '⌛ Limit reset', 'callback_data': 'reset'}],
        # [{'text': skip_sign_in, 'callback_data': 'skip_sign_in'}],
        [{'text': '↩ Back', 'callback_data': 'back'}]
    ]


# @inline_markup
# def last_seen_filter(settings):
#     markup = []
#     for status in LastSeenEnum:
#         text = status.verbose_name
#         val = status.value
#         if val == settings.last_seen:
#             text += '  💚'
#         markup.append([{'text': text, 'callback_data': str(val)}])
#     markup.append([{'text': '↩ Back', 'callback_data': 'settings_menu'}])
#     return markup


@inline_markup
def scrape_menu():
    return [
        [{'text': '✈ Run', 'callback_data': 'start'}],
        # [{'text': '🔁 Run every 24 hours', 'callback_data': 'repeatedly'}],
        [{'text': '↩ Back', 'callback_data': 'to_menu'}],
    ]


@inline_markup
def groups():
    return [
        [{'text': '📝 Add', 'callback_data': 'add'}],
        [{'text': '💾 Groups', 'callback_data': 'list'}],
        [{'text': '↩ Back', 'callback_data': 'to_menu'}],
    ]


@inline_markup
def groups_list(groups, page=1):
    items = [(group.id, group.label) for group in groups]
    rows = general_list(items, page)
    rows.append([{'text': '↩ Back', 'callback_data': 'back'}])
    return rows


@inline_markup
def api_configs(items, page=1):
    items = [(item.id, item.api_id) for item in items]
    rows = general_list(items, page)
    rows.append([{'text': '📝 Add new', 'callback_data': 'add'}])
    rows.append([{'text': '↩ Back', 'callback_data': 'back'}])
    return rows


@inline_markup
def api_config_detail():
    return [
        [{'text': '📡 Verify', 'callback_data': 'verify'}],
        [{'text': '🗑 Delete', 'callback_data': 'delete'}],
        [{'text': '↩ Back', 'callback_data': 'back'}]
    ]


@inline_markup
def group_detail(group):
    status = '⚡️ Enabled' if group.enabled else '💤 Disabled'
    return [
        [{'text': status, 'callback_data': 'status'}],
        [{'text': '❤️  Set as target', 'callback_data': 'group_to'}],
        [{'text': '🗑 Delete', 'callback_data': 'delete'}],
        [{'text': '↩ Back', 'callback_data': 'back'}]
    ]


@inline_markup
def task_already_running():
    return [
        [{'text': '☠️Stop', 'callback_data': 'stop'}],
        [{'text': '↩ Back', 'callback_data': 'to_menu'}]
    ]


@inline_markup
def max_btn(val):
    return [
        [{'text': '📶 Max', 'callback_data': str(val)}]
    ]


@inline_markup
def stop_run():
    return [
        [{'text': '⏻️Stop', 'callback_data': 'stop_run'}],
    ]



# @inline_markup
# def list(items, page=1):
#     rows = general_list(items, page)
#     return rows
#
#
# @inline_markup
# def multiple_groups(items, selected=[], page=1):
#     total_len = len(items)
#     start = (page - 1) * PAGE_SIZE
#     end = page * PAGE_SIZE
#     items = items[start:end]
#     rows = []
#     for id, name in items:
#         icon = '☑' if id in selected else '◻'
#         rows.append([{'text': '{} {}'.format(name, icon), 'callback_data': id}])
#     if len(items) < total_len:
#         last_page = math.ceil(total_len / PAGE_SIZE)
#         prev_page = page - 1 or last_page
#         next_page = page + 1
#         if next_page > last_page:
#             next_page = 1
#         rows.append([
#             {'text': '⏪ Prev', 'callback_data': 'page_{}'.format(prev_page)},
#             {'text': 'Page {}'.format(page), 'callback_data': 'blank'},
#             {'text': '⏩ Next', 'callback_data': 'page_{}'.format(next_page)}
#         ])
#     rows.append([{'text': '✅ Done', 'callback_data': 'done'}])
#     return rows
