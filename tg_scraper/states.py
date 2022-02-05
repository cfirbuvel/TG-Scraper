from aiogram.dispatcher.filters.state import State, StatesGroup


class Menu(StatesGroup):
    main = State()


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
    run = State()
    invites_limit = State()
    limit_reset = State()
    last_seen_filter = State()
    join_delay = State()
    add_sessions = State()


class Scrape(StatesGroup):
    main = State()
    groups = State()
    add_group = State()
    groups_list = State()
    group_detail = State()
    task_running = State()

    # target_group_link = State()
    add_limit = State()

    enter_code = State()
    resend_code = State()

    select_group = State()
    select_multiple_groups = State()
    # group_from = State()
    # group_to = State()

