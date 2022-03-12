from aiogram.dispatcher.filters import Filter


class CallbackData(Filter):

    def __init__(self, *args):
        self.data = list(args)

    async def check(self, callback_query):
        return callback_query.data in self.data