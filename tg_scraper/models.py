import asyncio
from configparser import ConfigParser
import datetime
import enum

from aiogram.utils.markdown import quote_html
from telethon.errors.rpcerrorlist import ApiIdInvalidError, PhoneNumberBannedError, FloodWaitError
from tortoise import fields, Tortoise
from tortoise.exceptions import DoesNotExist
from tortoise.models import Model


class Account(Model):

    # class Status(enum.IntEnum):
    #     OK = 0
    #     INVALID_DETAILS = 1
    #     PHONE_BANNED = 2
    #     FLOOD_WAIT = 3

    id = fields.IntField(pk=True)
    api_id = fields.IntField()
    api_hash = fields.CharField(max_length=128)
    phone = fields.CharField(max_length=20, unique=True)
    name = fields.CharField(max_length=255)
    # status = fields.IntEnumField(enum_type=Status, default=Status.OK)
    # banned_until = fields.DatetimeField(null=True)
    session_string = fields.TextField(null=True)

    # async def set_error_status(self, exception):
    #     status_map = {
    #         ApiIdInvalidError: self.Status.INVALID_DETAILS,
    #         PhoneNumberBannedError: self.Status.PHONE_BANNED,
    #         FloodWaitError: self.Status.FLOOD_WAIT,
    #     }
    #     ex_class = type(exception)
    #     self.status = status_map[ex_class]
    #     if ex_class == FloodWaitError:
    #         self.banned_for = exception.seconds
    #     await self.save()

    # def get_status_display(self):
    #     map = {
    #         self.Status.OK.value: 'Ok', self.Status.INVALID_DETAILS.value: 'Invalid data',
    #         self.Status.PHONE_BANNED.value: 'Phone number banned', self.Status.FLOOD_WAIT.value: 'Flood wait'
    #     }
    #     res = map[self.status]
    #     if self.status == self.Status.FLOOD_WAIT and self.banned_for is not None:
    #         res += ' for *{}* seconds'.format(self.banned_for)
    #     return res

    def get_detail_text(self):
        res = (f'Name: <b>{quote_html(self.name)}</b>\n'
               f'Phone: <b>{quote_html(self.phone)}</b>\n\n'
               f'API id: <b>{quote_html(self.api_id)}</b>\n'
               f'API hash: <b>{quote_html(self.api_hash)}</b>')
        # if self.banned_until:
        #     until = self.banned_until.strftime('_%d %b, %y_ *%H:%M*')
        #     res += f'\n\nBanned until: {until}'
        return res

    def __str__(self):
        return '{} {}'.format(self.name, self.phone)


class Settings(Model):

    class Status(enum.IntEnum):
        ANY_TIME = 0
        RECENTLY = 1
        WITHIN_A_WEEK = 7
        WITHIN_A_MONTH = 30

        @property
        def verbose_name(self):
            return self.name.replace('_', ' ').capitalize()

    id = fields.IntField(pk=True)
    status_filter = fields.IntEnumField(enum_type=Status, default=Status.ANY_TIME)
    join_delay = fields.IntField(default=60)

    def details_msg(self):
        msg = ('⚙  Settings\n\n'
               'Last seen: <b>{}</b>\n'
               'Delay between adding accounts: <b>{}</b> seconds').format(self.status_filter.verbose_name,
                                                                          self.join_delay)
        return msg


# class Run(Model):
#     id = fields.IntField(pk=True)
#     chat_id = fields.IntField(unique=True)
#     task_name = fields.CharField(max_length=68)
#     last_time = fields.DatetimeField(null=True)
#     # accounts = fields.ManyToManyField('models.Account', related_name='runs')
#
#     def update_time(self):
#         self.last_time = datetime.datetime.now()
#         self.save()
#
#     async def is_active(self):
#         return any(task.get_name() == self.task_name for task in asyncio.all_tasks())


# class Participant(Model):
#     id = fields.IntField(pk=True)
#     user_id = fields.IntField()
#     added = fields.BooleanField(default=False)
#     run = fields.ForeignKeyField('models.Run', related_name='participants', on_delete=fields.CASCADE)


async def init_db():
    # Here we create a SQLite DB using file "db.sqlite3"
    #  also specify the app name of "models"
    #  which contain models from "app.models"
    config = ConfigParser()
    config.read('config.ini')
    await Tortoise.init(
        db_url='sqlite://db.sqlite3',
        modules={'models': ['tg_scraper.models',]}
    )
    # Generate the schema
    await Tortoise.generate_schemas()
    try:
        await Settings.get()
    except DoesNotExist:
        await Settings.create()
