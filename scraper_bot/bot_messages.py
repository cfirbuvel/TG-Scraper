
class BotMessages:
    MAIN = 'Main Menu'
    USER_USERNAME = 'Please enter username:'
    USER_API_ID = 'Please enter user API id:'
    USER_API_HASH = 'Please enter user API hash:'
    USER_PHONE = 'Please enter user phone number:'
    USER_PHONE_INVALID = 'Entered phone is not valid.\n' \
                         'Please enter correct phone number:'
    USER_SAVED = 'User *{}* was created!'
    USERS_LIST = 'Please select a user:'
    SELECTED_USER = 'User:\n' \
                    '_Username_: {username}\n' \
                    '_API id_: {api_id}\n' \
                    '_API hash_: {api_hash}\n' \
                    '_Phone number_: {phone}'
    USER_DELETED = 'User _{}_ was deleted!'
    SCRAPE_STOPPED = 'Scrape will be stopped in 1 minute'
    SCRAPE_CANCELLED = 'Scrape process was cancelled.'
    SCRAPE = 'Scrape process'
    SCRAPE_REFUSED = 'Cannot start while previous scrape is not completed!'
    OK_MSG = 'OK'

