import asyncio
import enum
import functools

from aiogram.types.inline_keyboard import InlineKeyboardButton, InlineKeyboardMarkup
from telethon.utils import get_display_name
from tortoise import run_async

from tg_scraper import Answer
from tg_scraper.models import Account, Settings


class InlineKeyboardMeta(type):

    def __init__(cls, *args, **kwargs):
        pass

    def _build_markup(cls, rows):
        keyboard = []
        for row in rows:
            keyboard.append([InlineKeyboardButton(**btn_data) for btn_data in row])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @property
    def main_menu(cls):
        return cls._build_markup([
            [{'text': '🤖  Add account', 'callback_data': 'add_acc'}],
            [{'text': '🗂  Accounts', 'callback_data': 'list_accs'}],
            [{'text': '⚙️  Settings', 'callback_data': 'settings'}],
            [{'text': '💥  Start scrape', 'callback_data': 'scrape'}],
        ])

    @property
    def back(cls):
        return cls._build_markup([
            [{'text': '↩ Back', 'callback_data': 'back'}]
        ])

    @property
    def cancel_back(cls):
        return cls._build_markup([
            [{'text': '❌ Cancel', 'callback_data': 'to_menu'}, {'text': '↩ Back', 'callback_data': 'back'}],
        ])

    @property
    def yes_no(cls):
        return cls._build_markup([
            [{'text': '✖️ No', 'callback_data': 'no'}, {'text': '✔️ Yes', 'callback_data': 'yes'}]
        ])

    @property
    def skip(cls):
        return cls._build_markup([
            [{'text': 'Skip', 'callback_data': 'skip'}]
        ])

    @property
    def enter_code(cls):
        return cls._build_markup([
            [{'text': 'Resend code', 'callback_data': Answer.RESEND}],
            [{'text': 'Skip', 'callback_data': Answer.SKIP}],
            # [{'text': '☠️ Stop Run', 'callback_data': Answer.STOP}],
        ])

    @staticmethod
    def accounts(data):
        markup = InlineKeyboardMarkup()
        for i, acc in enumerate(data, 1):
            text = '{}.  {}'.format(i, str(acc))
            btn = InlineKeyboardButton(text, callback_data=str(acc.id))
            markup.row(btn)
        markup.row(InlineKeyboardButton('↩ Back', callback_data='to_menu'))
        return markup

    @property
    def account_detail(cls):
        return cls._build_markup([
            [{'text': '🚫 Delete', 'callback_data': 'delete'}],
            [{'text': '↩ Back', 'callback_data': 'back'}]
        ])

    @property
    def settings(cls):
        return cls._build_markup([
            [{'text': '🚷  Last seen filter', 'callback_data': 'status_filter'}],
            [{'text': '⏱  Accounts invite delay', 'callback_data': 'join_delay'}],
            [{'text': '↩ Back', 'callback_data': 'to_menu'}]
        ])

    def status_filter(cls, current_value):
        markup = []
        for status in Settings.Status:
            text = status.verbose_name
            val = status.value
            if val == current_value:
                text += '  💚'
            markup.append([{'text': text, 'callback_data': str(val)}])
        markup.append([{'text': '↩ Back', 'callback_data': 'settings'}])
        return cls._build_markup(markup)

    @property
    def scrape_menu(cls):
        return cls._build_markup([
            [{'text': 'Run', 'callback_data': 'run_scrape'}],
            [{'text': 'Run every day (until all users added)', 'callback_data': 'run_scrape_daily'}],
            [{'text': '↩ Back', 'callback_data': 'to_menu'}],
        ])

    @property
    def run_control(cls):
        return cls._build_markup([
            [{'text': '☠️ Stop Run', 'callback_data': Answer.STOP}],
        ])

    @staticmethod
    def groups(data, *, page=1, per_page=50, back_btn=False):
        groups = list(data.items())
        markup = InlineKeyboardMarkup()
        # pager = None
        # if len(groups) > per_page:
        pager = []
        start = (page - 1) * per_page
        end = page * per_page
        if page > 1:
            pager.append(InlineKeyboardButton('⏪ Prev', callback_data='prev'))
        if len(groups) > end:
            pager.append(InlineKeyboardButton('⏩ Next', callback_data='next'))
        groups = groups[start:end]
        for i, data in enumerate(groups, start + 1):
            id, name = data
            markup.row(InlineKeyboardButton('{}.  {}'.format(i, name), callback_data=id))
        if pager:
            markup.row(*pager)
        if back_btn:
            markup.row(InlineKeyboardButton('↩ Back', callback_data='back'))
        markup.row(InlineKeyboardButton('☠️ Stop Run', callback_data=Answer.STOP))
        return markup


class InlineKeyboard(metaclass=InlineKeyboardMeta):
    pass
