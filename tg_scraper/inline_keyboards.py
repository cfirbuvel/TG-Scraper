import asyncio
import functools

from aiogram.types.inline_keyboard import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import escape_md
from tortoise import run_async

from tg_scraper.models import Account


class InlineKeyboard(InlineKeyboardMarkup):
    rows = None

    def __init__(self, *args, **kwargs):
        self.rows = kwargs.pop('rows', self.rows)
        super().__init__(*args, **kwargs)
        self.build_keyboard()

    def build_keyboard(self):
        for row in self.rows:
            buttons = []
            for item in row:
                buttons.append(InlineKeyboardButton(**item))
            self.row(*buttons)
    # @classmethod
    # async def create(cls):
    #     self = cls()
    #     await self.build_keyboard()
    #     return self


class MainMenuKeyboard(InlineKeyboard):
    rows = [
        [{'text': 'Add account', 'callback_data': 'add_acc'}],
        [{'text': 'Accounts', 'callback_data': 'list_accs'}],
        [{'text': 'Start scrape', 'callback_data': 'scrape'}],
    ]


class BackKeyboard(InlineKeyboard):
    rows = [
        [{'text': '↩ Back', 'callback_data': 'back'}]
    ]


class CancelBackKeyboard(InlineKeyboard):
    rows = [
        [{'text': 'Cancel', 'callback_data': 'cancel'}, {'text': '↩ Back', 'callback_data': 'back'}],
    ]


class YesNoKeyboard(InlineKeyboard):
    rows = [
        [{'text': 'No', 'callback_data': 'no'}, {'text': 'Yes', 'callback_data': 'yes'}]
    ]


class SkipKeyboard(InlineKeyboard):
    rows = [
        [{'text': 'Skip', 'callback_data': 'skip'}]
    ]


class EnterCodeKeyboard(InlineKeyboard):
    rows = [
        [{'text': 'Resend code', 'callback_data': 'resend'}],
        [{'text': 'Skip', 'callback_data': 'skip'}]
    ]


class AccountsKeyboard(InlineKeyboard):

    def __init__(self, accounts, *args, **kwargs):
        self.accounts = accounts
        super().__init__(*args, **kwargs)

    def build_keyboard(self):
        for i, acc in enumerate(self.accounts):
            text = '{}.  {}'.format(i, acc.get_label(escape_markdown=False))
            btn = InlineKeyboardButton(text, callback_data=str(acc.id))
            # btn = {'text': text, 'callback_data': str(acc.id)}
            self.row(btn)
        self.row(InlineKeyboardButton('↩ Back', callback_data='back'))


class ScrapeKeyboard(InlineKeyboard):
    rows = [
        [{'text': 'Run', 'callback_data': 'run_scrape'}],
        [{'text': 'Repeat every 24 hours', 'callback_data': 'run_scrape_repeat'}],
        [{'text': '↩ Back', 'callback_data': 'back'}],
    ]


class GroupsKeyboard(InlineKeyboardMarkup):

    per_page = 50

    def __init__(self, groups_data, page=1, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.build_keyboard(groups_data, page)

    def build_keyboard(self, groups, page):
        groups = list(groups.items())
        pager = None
        if len(groups) > self.per_page:
            start = (page - 1) * self.per_page
            end = page * self.per_page
            pager = []
            if page > 1:
                pager.append(InlineKeyboardButton('⏪', callback_data='prev'))
            pager.append(InlineKeyboardButton('Page {}'.format(page), callback_data='blank'))
            if len(groups) > end:
                pager.append(InlineKeyboardButton('⏩', callback_data='next'))
            groups = groups[start:end]
        for key, name in groups:
            self.row(InlineKeyboardButton('{}.  {}'.format(key, name), callback_data=key))
        if pager:
            self.row(*pager)
        self.row(InlineKeyboardButton('↩ Back', callback_data='back'))
