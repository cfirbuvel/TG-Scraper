import math
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup


def create_main_menu_keyboard():
    reply_markup = [
        [InlineKeyboardButton('Add user', callback_data='add_user')],
        [InlineKeyboardButton('List users', callback_data='list_users')],
        [InlineKeyboardButton('Start scrape', callback_data='start_scrape')]
    ]
    return InlineKeyboardMarkup(reply_markup)


def scrape_keyboard():
    reply_markup = [
        [InlineKeyboardButton('Scrape', callback_data='normal_scrape')],
        [InlineKeyboardButton('Scrape every 24 hours', callback_data='scrape_24')],
        [InlineKeyboardButton('↩ Back', callback_data='back')]
    ]
    return InlineKeyboardMarkup(reply_markup)


def scrape_type_keyboard():
    reply_markup = [
        [InlineKeyboardButton('Scrape from all groups', callback_data='all')],
        [InlineKeyboardButton('Scrape from specific group', callback_data='spec')],
        [InlineKeyboardButton('↩ Back', callback_data='back')]
    ]
    return InlineKeyboardMarkup(reply_markup)


def create_back_btn():
    reply_markup = [
        [InlineKeyboardButton('↩ Back', callback_data='back')]
    ]
    return InlineKeyboardMarkup(reply_markup)


def create_back_keyboard(one_time=True):
    reply_markup = [
        [KeyboardButton('↩ Back')]
    ]
    return ReplyKeyboardMarkup(reply_markup, one_time_keyboard=one_time, resize_keyboard=True)


def create_user_list_keyboard(objects, page_num=1, page_len=15):
    buttons = []
    prev_page = None
    next_page = None
    if len(objects) > page_len:
        max_pages = math.ceil(len(objects) / float(page_len))
        objects = objects[(page_num - 1) * page_len: page_num * page_len]
        prev_page = page_num - 1 if page_num > 1 else None
        next_page = page_num + 1 if page_num < max_pages else None
    for name, id in objects:
        callback_data = 'select|{}'.format(id)
        button = [InlineKeyboardButton(name, callback_data=callback_data)]
        buttons.append(button)
    if prev_page:
        callback_data = 'page|{}'.format(prev_page)
        button = [InlineKeyboardButton('◀️ Previous', callback_data=callback_data)]
        buttons.append(button)
    if next_page:
        callback_data = 'page|{}'.format(next_page)
        button = [InlineKeyboardButton('▶️ Next', callback_data=callback_data)]
        buttons.append(button)
    back_btn = [InlineKeyboardButton('↩ Back', callback_data='back|')]
    buttons.append(back_btn)
    return InlineKeyboardMarkup(buttons)


def create_selected_user_keyboard(user_id):
    buttons = [
        [InlineKeyboardButton('Delete user', callback_data='delete|{}'.format(user_id))],
        [InlineKeyboardButton('↩ Back', callback_data='back|')]
    ]
    return InlineKeyboardMarkup(buttons)


def scrape_not_completed_keyboard():
    buttons = [
        [InlineKeyboardButton('↩ Back', callback_data='back')],
        [InlineKeyboardButton('❌ Cancel Scrape', callback_data='cancel')]
    ]
    return InlineKeyboardMarkup(buttons)


def create_phone_invalid_keyboard():
    buttons = [
        [KeyboardButton('Enter again')],
        [KeyboardButton('Resend code')],
        [KeyboardButton('Skip user')],
        [KeyboardButton('❌ Cancel')]
    ]
    return ReplyKeyboardMarkup(buttons)


def skip_user_keyboard():
    buttons = [
        [KeyboardButton('Skip user')],
        [KeyboardButton('❌ Cancel')]
    ]
    return ReplyKeyboardMarkup(buttons)


def stop_scrape_keyboard():
    buttons = [
        [KeyboardButton('❌ Stop')]
    ]
    return ReplyKeyboardMarkup(buttons, one_time_keyboard=True, resize_keyboard=True)


def continue_keyboard():
    buttons = [
        [KeyboardButton('Continue')],
        [KeyboardButton('❌ Cancel')]
    ]
    return ReplyKeyboardMarkup(buttons)


action_keyboards_map = {
    'phone_invalid': create_phone_invalid_keyboard(),
    'skip_user': skip_user_keyboard(),
    'stop_scrape': stop_scrape_keyboard(),
    'continue': continue_keyboard()
}