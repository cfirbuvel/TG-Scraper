from aiogram.dispatcher.filters.state import State, StatesGroup


class MenuState(StatesGroup):
    MAIN = State()


class AccountState(StatesGroup):
    PHONE = State()
    API_ID = State()
    API_HASH = State()
    NAME = State()

    ENTER_CODE = State()
    RESEND_CODE = State()

    LIST = State()
    DELETE = State()
    # should_restart = State()
    # should_create = State()


class ScrapeState(StatesGroup):
    MAIN = State()
    RUNNING = State()


class SelectGroupState(StatesGroup):
    GROUP_FROM = State()
    GROUP_TO = State()
