import re
import threading

from telegram import ParseMode

from bot_enums import BotStates
from bot_messages import BotMessages
from bot_models import Account, db, reload_db
import bot_keyboards as keyboards
from bot_helpers import JsonRedis, get_redis_key
from scraper import scrape_process, BotResp


def on_error(bot, update, error):
    print('Error: {}'.format(error))


def on_start(bot, update):
    chat_id = update.effective_chat.id
    reply_markup = keyboards.create_main_menu_keyboard()
    bot.send_message(chat_id, BotMessages.MAIN, reply_markup=reply_markup)
    return BotStates.BOT_MENU


def on_menu(bot, update, user_data):
    chat_id = update.effective_chat.id
    msg_id = update.effective_message.message_id
    query = update.callback_query
    callback_data = query.data
    if callback_data == 'add_user':
        bot.send_message(chat_id, BotMessages.USER_USERNAME)
        query.answer()
        return BotStates.BOT_USER_USERNAME
    elif callback_data == 'list_users':
        accounts = Account.select(Account.username, Account.id).tuples()
        reply_markup = keyboards.create_user_list_keyboard(accounts)

        bot.edit_message_text(BotMessages.USERS_LIST, chat_id, msg_id, reply_markup=reply_markup)
        query.answer()
        return BotStates.BOT_USERS_LIST
    elif callback_data == 'start_scrape':
        query.answer()
        session = JsonRedis(host='localhost', port=6379, db=0)
        session.clear_keys('bot_msg', 'scraper_msg')
        t = threading.Thread(target=scrape_process, args=(session,))
        t.start()
        while True:
            action, msg = get_redis_key(session, 'bot_msg')
            if action == BotResp.MSG:
                bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN)
            elif action == BotResp.ACTION:
                bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN)
                user_data['session'] = session
                return BotStates.BOT_SCRAPE
            else:
                bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN)
                try:
                    del user_data['session']
                except KeyError:
                    pass
                session.clear_keys('bot_msg', 'scraper_msg')
                reply_markup = keyboards.create_main_menu_keyboard()
                bot.send_message(chat_id, BotMessages.MAIN, reply_markup=reply_markup)
                return BotStates.BOT_MENU


def on_bot_scrape(bot, update, user_data):
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    session = user_data['session']
    session.json_set('scraper_msg', text)
    while True:
        action, msg = get_redis_key(session, 'bot_msg')
        if action == BotResp.MSG:
            bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN)
        elif action == BotResp.ACTION:
            bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN)
            user_data['session'] = session
            return BotStates.BOT_SCRAPE
        else:
            bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN)
            try:
                del user_data['session']
            except KeyError:
                pass
            session.clear_keys('bot_msg', 'scraper_msg')
            reply_markup = keyboards.create_main_menu_keyboard()
            bot.send_message(chat_id, BotMessages.MAIN, reply_markup=reply_markup)
            return BotStates.BOT_MENU


def on_user_username(bot, update, user_data):
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    user_data['user_creds'] = {'username': text}
    bot.send_message(chat_id, BotMessages.USER_API_ID)
    return BotStates.BOT_USER_ID


def on_user_id(bot, update, user_data):
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    user_data['user_creds']['api_id'] = text
    bot.send_message(chat_id, BotMessages.USER_API_HASH)
    return BotStates.BOT_USER_HASH


def on_user_hash(bot, update, user_data):
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    user_data['user_creds']['api_hash'] = text
    bot.send_message(chat_id, BotMessages.USER_PHONE)
    return BotStates.BOT_USER_PHONE


def on_user_phone(bot, update, user_data):
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    match = re.search(r'(\+?\d{1,3})?\d{7,13}', text)
    if not match:
        bot.send_message(chat_id, BotMessages.USER_PHONE_INVALID)
        return BotStates.BOT_USER_PHONE
    else:
        acc_data = user_data['user_creds']
        account = Account.create(username=acc_data['username'], api_id=acc_data['api_id'],
                                 api_hash=acc_data['api_hash'], phone=text)
        msg = BotMessages.USER_SAVED.format(account.username)
        bot.send_message(chat_id, msg, reply_markup=keyboards.create_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return BotStates.BOT_MENU


def on_user_list(bot, update):
    chat_id = update.effective_chat.id
    query = update.callback_query
    action, data = query.data.split('|')
    msg_id = query.message.message_id
    if action == 'back':
        bot.edit_message_text(BotMessages.MAIN, chat_id, msg_id, reply_markup=keyboards.create_main_menu_keyboard())
        query.answer()
        return BotStates.BOT_MENU
    elif action == 'page':
        accounts = Account.select(Account.username, Account.id).tuples()
        reply_markup = keyboards.create_user_list_keyboard(accounts, page_num=int(data))
        bot.edit_message_text(BotMessages.USERS_LIST, chat_id, msg_id, reply_markup=reply_markup)
        query.answer()
        return BotStates.BOT_USERS_LIST
    elif action == 'select':
        account = Account.get(id=data)
        msg_data = {
            'api_id': account.api_id, 'api_hash': account.api_hash,
            'username': account.username, 'phone': account.phone
        }
        msg = BotMessages.SELECTED_USER.format(**msg_data)
        reply_markup = keyboards.create_selected_user_keyboard(data)
        bot.edit_message_text(msg, chat_id, msg_id, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        query.answer()
        return BotStates.BOT_USER_SELECTED


def on_selected_user(bot, update):
    chat_id = update.effective_chat.id
    query = update.callback_query
    action, data = query.data.split('|')
    msg_id = query.message.message_id
    if action == 'delete':
        account = Account.get(id=data)
        username = account.username
        account.delete_instance()
        msg = BotMessages.USER_DELETED.format(username)
        bot.edit_message_text(msg, chat_id, msg_id, reply_markup=keyboards.create_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
        query.answer()
        return BotStates.BOT_MENU
    elif action == 'back':
        accounts = Account.select(Account.username, Account.id).tuples()
        reply_markup = keyboards.create_user_list_keyboard(accounts)
        bot.edit_message_text(BotMessages.USERS_LIST, chat_id, msg_id, reply_markup=reply_markup)
        query.answer()
        return BotStates.BOT_USERS_LIST

