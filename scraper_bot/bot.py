from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, Filters, MessageHandler, Updater

from bot_models import create_tables, db
import bot_handlers as handlers
import bot_helpers as helpers
from bot_enums import BotStates


def main():
    conversation_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', handlers.on_start),
        ],
        states={
            BotStates.BOT_INIT: [
                CommandHandler('start', handlers.on_start)
            ],
            BotStates.BOT_MENU: [
                CallbackQueryHandler(handlers.on_menu, pass_user_data=True)
            ],
            BotStates.BOT_SCRAPE: [
                MessageHandler(Filters.text, handlers.on_bot_scrape, pass_user_data=True)
            ],
            BotStates.BOT_USER_USERNAME: [
                MessageHandler(Filters.text, handlers.on_user_username, pass_user_data=True)
            ],
            BotStates.BOT_USER_ID: [
                MessageHandler(Filters.text, handlers.on_user_id, pass_user_data=True)
            ],
            BotStates.BOT_USER_HASH: [
                MessageHandler(Filters.text, handlers.on_user_hash, pass_user_data=True)
            ],
            BotStates.BOT_USER_PHONE: [
                MessageHandler(Filters.text, handlers.on_user_phone, pass_user_data=True)
            ],
            BotStates.BOT_USERS_LIST: [
                CallbackQueryHandler(handlers.on_user_list)
            ],
            BotStates.BOT_USER_SELECTED: [
                CallbackQueryHandler(handlers.on_selected_user)
            ],
        },
        fallbacks=[
            CommandHandler('start', handlers.on_start),

        ],
    )
    config = helpers.read_config('config.ini')
    bot_token = config['bot_token']
    bot_token = bot_token.strip()
    updater = Updater(token=bot_token)
    updater.dispatcher.add_handler(conversation_handler)
    updater.dispatcher.add_error_handler(handlers.on_error)
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    create_tables(db)
    main()