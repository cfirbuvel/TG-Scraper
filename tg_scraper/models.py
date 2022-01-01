import asyncio
import datetime
import random

from aiogram.utils.markdown import quote_html
from tortoise import fields, Tortoise
from tortoise.models import Model

from .conf import Settings


class Account(Model):
    id = fields.IntField(pk=True)
    api_id = fields.IntField()
    api_hash = fields.CharField(max_length=128)
    phone = fields.CharField(max_length=20, unique=True)
    name = fields.CharField(max_length=255)
    session_string = fields.TextField(null=True)
    invites_max = fields.IntField(null=True)
    invites_sent = fields.IntField(default=0)
    last_invite_date = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    async def invites_incr(self, num=1):
        self.invites_sent += num
        self.last_invite_date = datetime.datetime.now()
        await self.save()

    @property
    def can_invite(self):
        return self.invites_sent < self.invites_max

    @property
    def invites_left(self):
        return self.invites_max - self.invites_sent

    async def refresh_invites(self):
        limit_reset = Settings().limit_reset
        if not self.can_invite:
            if self.last_invite_date + datetime.timedelta(days=limit_reset) >= datetime.datetime.now():
                self.invites_sent = 0
                await self.save()

    @property
    def safe_name(self):
        return quote_html(self.name)

    def get_detail_msg(self):
        msg = (f'Name: <b>{self.safe_name}</b>\n'
               f'Phone: <b>{self.phone}</b>\n'
               f'API id: <b>{self.api_id}</b>\n'
               f'API hash: <b>{self.api_hash}</b>\n\n'
               f'Invites limit: <b>{self.invites_max}</b>\n'
               f'Invites sent: <b>{self.invites_sent}</b>')
        if not self.can_invite:
            reset_at = self.last_invite_date + datetime.timedelta(days=Settings().limit_reset)
            msg += '\nInvites reset at: <b>{}</b>'.format(reset_at.strftime('%d-%m-%Y %H:%M'))
        return msg

    # def __str__(self):
    #     return '{} {}'.format(self.name, self.phone)


async def init_db():
    await Tortoise.init(
        db_url='sqlite://db.sqlite3',
        modules={'models': ['tg_scraper.models']}
    )
    await Tortoise.generate_schemas()
