import re
import threading

from telegram import ParseMode, ReplyKeyboardRemove
from telegram.utils.helpers import escape_markdown

from bot_enums import BotStates
from bot_messages import BotMessages
from bot_models import Account, db
import bot_keyboards as keyboards
from bot_helpers import JsonRedis, SessionKeys, get_redis_key, set_exit_key, clear_session
from scraper import default_scrape, scheduled_scrape, BotResp


def on_error(bot, update, error):
    print('Error: {}'.format(error))


def on_start(bot, update):
    chat_id = update.effective_chat.id
    reply_markup = keyboards.create_main_menu_keyboard()
    bot.send_message(chat_id, BotMessages.MAIN, reply_markup=reply_markup)
    return BotStates.BOT_MENU


def on_cancel(bot, update, user_data):
    print('cancel debug')
    chat_id = update.effective_chat.id
    session = user_data['session']
    set_exit_key(session)
    msg = BotMessages.SCRAPE_STOPPED
    reply_markup = keyboards.create_main_menu_keyboard()
    bot.send_message(chat_id, msg, reply_markup=reply_markup)
    return BotStates.BOT_MENU


def on_menu(bot, update, user_data):
    chat_id = update.effective_chat.id
    msg_id = update.effective_message.message_id
    query = update.callback_query
    callback_data = query.data
    if callback_data == 'add_user':
        bot.send_message(chat_id, BotMessages.USER_USERNAME, reply_markup=keyboards.create_back_keyboard())
        query.answer()
        return BotStates.BOT_USER_USERNAME
    elif callback_data == 'list_users':
        accounts = Account.select(Account.username, Account.id).tuples()
        reply_markup = keyboards.create_user_list_keyboard(accounts)

        bot.edit_message_text(BotMessages.USERS_LIST, chat_id, msg_id, reply_markup=reply_markup)
        query.answer()
        return BotStates.BOT_USERS_LIST
    elif callback_data == 'start_scrape':
        session = user_data.get('session')
        print(session)
        if session:
            print(session.json_get(SessionKeys.RUNNING))
        if session and session.json_get(SessionKeys.RUNNING):
            reply_markup = keyboards.scrape_not_completed_keyboard()
            bot.edit_message_text(BotMessages.SCRAPE_REFUSED, chat_id, msg_id, reply_markup=reply_markup)
            return BotStates.BOT_SCRAPE_STOP
        reply_markup = keyboards.scrape_keyboard()
        bot.edit_message_text(BotMessages.SCRAPE, chat_id, msg_id, reply_markup=reply_markup)
        query.answer()
        return BotStates.BOT_SCRAPE_SELECT


def on_bot_scrape_stop(bot, update, user_data):
    chat_id = update.effective_chat.id
    msg_id = update.effective_message.message_id
    query = update.callback_query
    callback_data = query.data
    if callback_data == 'back':
        msg = BotMessages.MAIN
    else:
        session = user_data['session']
        set_exit_key(session)
        msg = BotMessages.SCRAPE_STOPPED
    reply_markup = keyboards.create_main_menu_keyboard()
    bot.edit_message_text(msg, chat_id, msg_id, reply_markup=reply_markup)
    return BotStates.BOT_MENU


def bot_scrape_handler(bot, user_data, chat_id):
    session = user_data['session']
    while True:
        action, msg, keyboard = get_redis_key(session, SessionKeys.BOT_MSG)
        if keyboard:
            keyboard = keyboards.action_keyboards_map.get(keyboard)
        else:
            keyboard = ReplyKeyboardRemove()
        if action == BotResp.MSG:
            bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        elif action == BotResp.ACTION:
            bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
            user_data['session'] = session
            return BotStates.BOT_SCRAPE
        else:
            bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
            if not session.json_get(SessionKeys.RUNNING):
                clear_session(session)
            # continuous = session.json_get(SessionKeys.CONTINUOUS)
            # if not continuous:
            #     try:
            #         del user_data['session']
            #     except KeyError:
            #         pass
            # keys_to_clear = (SessionKeys.SCRAPER_MSG, SessionKeys.BOT_MSG, SessionKeys.EXIT_THREAD)
            reply_markup = keyboards.create_main_menu_keyboard()
            bot.send_message(chat_id, BotMessages.MAIN, reply_markup=reply_markup)
            return BotStates.BOT_MENU


def on_bot_scrape_select(bot, update, user_data):
    chat_id = update.effective_chat.id
    # msg_id = update.effective_message.message_id
    query = update.callback_query
    callback_data = query.data
    session = JsonRedis(host='localhost', port=6379, db=0)
    session.clear_keys(SessionKeys.BOT_MSG, SessionKeys.SCRAPER_MSG)
    session.json_set(SessionKeys.RUNNING, True)
    user_data['session'] = session
    if callback_data == 'scrape_24':
        scheduled_scrape(user_data, 24)
    else:
        default_scrape(user_data)
    query.answer()
    return bot_scrape_handler(bot, user_data, chat_id)
    # return BotStates.BOT_SCRAPE

    # while True:
    #     action, msg, keyboard = get_redis_key(session, 'bot_msg')
    #     print('debug msg')
    #     print(msg)
    #     if keyboard:
    #         keyboard = keyboards.action_keyboards_map.get(keyboard)
    #     else:
    #         keyboard = ReplyKeyboardRemove()
    #     if action == BotResp.MSG:
    #         bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    #     elif action == BotResp.ACTION:
    #         bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    #         user_data['session'] = session
    #         return BotStates.BOT_SCRAPE
    #     else:
    #         bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    #         try:
    #             del user_data['session']
    #         except KeyError:
    #             pass
    #         session.clear_keys('bot_msg', 'scraper_msg')
    #         reply_markup = keyboards.create_main_menu_keyboard()
    #         bot.send_message(chat_id, BotMessages.MAIN, reply_markup=reply_markup)
    #         return BotStates.BOT_MENU


def on_bot_scrape(bot, update, user_data):
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    session = user_data['session']
    session.json_set(SessionKeys.SCRAPER_MSG, text)
    return bot_scrape_handler(bot, user_data, chat_id)
    # while True:
    #     action, msg, keyboard = get_redis_key(session, 'bot_msg')
    #     if keyboard:
    #         keyboard = keyboards.action_keyboards_map.get(keyboard)
    #     else:
    #         keyboard = ReplyKeyboardRemove()
    #     if action == BotResp.MSG:
    #         bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    #     elif action == BotResp.ACTION:
    #         bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    #         user_data['session'] = session
    #         return BotStates.BOT_SCRAPE
    #     else:
    #         bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    #         try:
    #             del user_data['session']
    #         except KeyError:
    #             pass
    #         session.clear_keys('bot_msg', 'scraper_msg')
    #         reply_markup = keyboards.create_main_menu_keyboard()
    #         bot.send_message(chat_id, BotMessages.MAIN, reply_markup=reply_markup)
    #         return BotStates.BOT_MENU


def on_user_username(bot, update, user_data):
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    if text == '↩ Back':
        reply_markup = keyboards.create_main_menu_keyboard()
        bot.send_message(chat_id, BotMessages.MAIN, reply_markup=reply_markup)
        return BotStates.BOT_MENU
    user_data['user_creds'] = {'username': text}
    bot.send_message(chat_id, BotMessages.USER_API_ID, reply_markup=keyboards.create_back_keyboard(False))
    return BotStates.BOT_USER_ID


def on_user_id(bot, update, user_data):
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    if text == '↩ Back':
        bot.send_message(chat_id, BotMessages.USER_USERNAME, reply_markup=keyboards.create_back_keyboard())
        return BotStates.BOT_USER_USERNAME
    user_data['user_creds']['api_id'] = text
    bot.send_message(chat_id, BotMessages.USER_API_HASH, reply_markup=keyboards.create_back_keyboard(False))
    return BotStates.BOT_USER_HASH


def on_user_hash(bot, update, user_data):
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    if text == '↩ Back':
        bot.send_message(chat_id, BotMessages.USER_API_ID, reply_markup=keyboards.create_back_keyboard(False))
        return BotStates.BOT_USER_ID
    user_data['user_creds']['api_hash'] = text
    bot.send_message(chat_id, BotMessages.USER_PHONE, reply_markup=keyboards.create_back_keyboard(False))
    return BotStates.BOT_USER_PHONE


def on_user_phone(bot, update, user_data):
    chat_id = update.effective_chat.id

    text = update.effective_message.text
    if text == '↩ Back':
        bot.send_message(chat_id, BotMessages.USER_API_HASH, reply_markup=keyboards.create_back_keyboard(False))
        return BotStates.BOT_USER_HASH
    match = re.search(r'(\+?\d{1,3})?\d{7,13}', text)
    if not match:
        bot.send_message(chat_id, BotMessages.USER_PHONE_INVALID, reply_markup=keyboards.create_back_keyboard(False))
        return BotStates.BOT_USER_PHONE
    else:
        acc_data = user_data['user_creds']
        account = Account.create(username=acc_data['username'], api_id=acc_data['api_id'],
                                 api_hash=acc_data['api_hash'], phone=text)
        username = escape_markdown(account.username)
        print('debug username')
        print(username)
        msg = BotMessages.USER_SAVED.format(username)
        bot.send_message(chat_id, msg, reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.MARKDOWN)
        bot.send_message(chat_id, BotMessages.MAIN, reply_markup=keyboards.create_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
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
        print(accounts)
        reply_markup = keyboards.create_user_list_keyboard(accounts, page_num=int(data))
        bot.edit_message_text(BotMessages.USERS_LIST, chat_id, msg_id, reply_markup=reply_markup)
        query.answer()
        return BotStates.BOT_USERS_LIST
    elif action == 'select':
        account = Account.get(id=data)
        msg_data = {
            'api_id': account.api_id, 'api_hash': account.api_hash,
            'username': escape_markdown(account.username), 'phone': account.phone
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
        username = escape_markdown(account.username)
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

