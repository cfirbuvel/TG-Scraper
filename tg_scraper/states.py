from aiogram.dispatcher.filters.state import State, StatesGroup


class Menu(StatesGroup):
    main = State()


class Groups(StatesGroup):
    main = State()
    add = State()
    list = State()
    detail = State()


class AddAccount(StatesGroup):
    phone = State()
    api_id = State()
    api_hash = State()
    name = State()


class Accounts(StatesGroup):
    list = State()
    detail = State()
    delete = State()


class Settings(StatesGroup):
    main = State()
    invites_limit = State()
    limit_reset = State()
    last_seen = State()
    join_delay = State()
    add_sessions = State()


class ApiConf(StatesGroup):
    main = State()
    detail = State()
    delete = State()
    enter_id = State()
    enter_hash = State()


class Scrape(StatesGroup):
    main = State()
    task_running = State()
    add_limit = State()
    enter_code = State()
    resend_code = State()
    select_group = State()
    select_multiple_groups = State()

