from aiogram.dispatcher.filters.state import State, StatesGroup


class MenuState(StatesGroup):
    main = State()


class AddAccountState(StatesGroup):
    phone = State()
    api_id = State()
    api_hash = State()
    name = State()


class AccountsState(StatesGroup):
    list = State()
    detail = State()
    delete = State()


class SettingsState(StatesGroup):
    main = State()
    status_filter = State()
    join_delay = State()


class ScrapeState(StatesGroup):
    main = State()
    running = State()

    enter_code = State()
    resend_code = State()

    group_from = State()
    group_to = State()

# class SelectGroupState(StatesGroup):
#     group_from = State()
#     group_to = State()
