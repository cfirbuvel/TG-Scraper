import asyncio
import datetime
import random

from aiogram.utils.markdown import quote_html
from tortoise import fields, Tortoise
from tortoise.models import Model


class Settings(Model):
    # api_id = fields.IntField(null=True)
    # api_hash = fields.CharField(max_length=50, null=True)
    last_seen = fields.IntField(default=0)
    join_delay = fields.IntField(default=60)
    invite_limit = fields.IntField(default=30)
    limit_reset_days = fields.IntField(default=30)
    enable_proxy = fields.BooleanField(default=True)

    def __str__(self):
        # api_id = self.api_id or 'Not set'
        # api_hash = self.api_hash or 'Not set'
        last_seen = self.last_seen or 'Any'
        return (f'⚙  Settings\n\n'
                # f'Api id: <code>{api_id}</code>\n'
                # f'Api hash: <code>{api_hash}</code>\n'
                f'Max last seen days: <code>{last_seen}</code>\n'
                f'Join delay: <code>{self.join_delay}</code> seconds\n'
                f'Session invite limit: <code>{self.invite_limit}</code>\n'
                f'Limit resets after: <code>{self.limit_reset_days}</code> days')
        # self.api_id or 'Not set'

    def get_relative_invite_limit(self):
        low = max(0, self.invite_limit - 5)
        high = min(50, self.invite_limit + 5)
        return random.randint(low, high)


class ApiConfig(Model):
    api_id = fields.IntField()
    hash = fields.CharField(max_length=50)
    active = fields.BooleanField(default=False)

    def __str__(self):
        verified = 'Yes ✅' if self.active else 'No ❌'
        return (f'Api id: <code>{self.api_id}</code>\n'
                f'Api hash: <code>{self.hash}</code>\n'
                f'Verified: {verified}')


class Proxy(Model):
    address = fields.CharField(max_length=2048)
    port = fields.IntField()
    username = fields.CharField(max_length=128)
    passwd = fields.CharField(max_length=64)


class Account(Model):
    api_id = fields.IntField()
    api_hash = fields.CharField(max_length=128)
    phone = fields.CharField(max_length=20, unique=True)
    name = fields.CharField(max_length=255)
    session_string = fields.TextField(null=True)
    invites_max = fields.IntField(null=True)
    invites_sent = fields.IntField(default=0)
    invites_reset_at = fields.DatetimeField(null=True)
    master = fields.BooleanField(default=False)
    auto_created = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        ordering = ['-master', '-created_at']

    async def incr_invites(self, num=1):
        self.invites_sent += num
        await self.save()

    @property
    def can_invite(self):
        return self.invites_sent < self.invites_max

    @property
    def invites_left(self):
        return self.invites_max - self.invites_sent

    async def refresh_invites(self):
        if not self.can_invite:
            reset_at = self.invites_reset_at.replace(tzinfo=None)
            if datetime.datetime.now() >= reset_at:
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
            msg += '\nInvites reset at: <b>{}</b>'.format(self.invites_reset_at.strftime('%d-%m-%Y %H:%M'))
        if self.auto_created:
            msg += '\n<i>Account was created automatically.</i>'
        if self.master:
            msg = '🎩 Main account\n' + msg
        return msg


class Group(Model):
    name = fields.CharField(max_length=128, null=True)
    link = fields.CharField(max_length=2048)
    users_count = fields.IntField(null=True)
    enabled = fields.BooleanField(default=True)
    is_target = fields.BooleanField(default=False)
    details = fields.CharField(max_length=256, null=True)

    @property
    def label(self):
        res = self.link.split('/')[-1]
        if self.is_target:
            res = '❤️  {}'.format(res)
        elif not self.enabled:
            res = '💤  {}'.format(res)
        return res

    def get_name(self):
        if self.name:
            res = '{} ({})'.format(quote_html(self.name), self.link)
        else:
            res = self.link
        if self.is_target:
            res = '❤️  {}'.format(res)
        return res

    @property
    def detail_msg(self):
        users_count = 'unknown' if self.users_count is None else self.users_count
        msg = ('{}\n\n'
               'Participants count: <b>{}</b>').format(self.get_name(), users_count)
        if self.details:
            msg += '\n\n❕ {}'.format(self.details)
        return msg


async def init_db():
    await Tortoise.init(
        db_url='sqlite://db.sqlite3',
        modules={'models': ['tg_scraper.models']}
    )
    await Tortoise.generate_schemas()
    if not await Settings.exists():
        await Settings.create()
