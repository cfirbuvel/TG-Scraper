from aiogram.dispatcher.filters.state import State, StatesGroup


class MenuState(StatesGroup):
    MAIN = State()


class AddAccountState(StatesGroup):
    PHONE = State()
    API_ID = State()
    API_HASH = State()
    NAME = State()


class ScrapeState(StatesGroup):
    MAIN = State()
    RUNNING = State()

    ENTER_CODE = State()
    RESEND_CODE = State()

    GROUP_FROM = State()
    GROUP_TO = State()


class AccountsState(StatesGroup):
    LIST = State()
    DETAIL = State()
    DELETE = State()


# class SelectGroupState(StatesGroup):
#     GROUP_FROM = State()
#     GROUP_TO = State()
