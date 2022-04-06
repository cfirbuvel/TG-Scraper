import asyncio
import datetime
import enum
import random

from aiogram.utils.markdown import quote_html
from tortoise import fields, timezone, Tortoise
from tortoise.expressions import F
from tortoise.models import Model


class Settings(Model):
    _cached = None

    class TimeUnit(enum.IntEnum):
        HOUR = 1
        DAY = 24
    # api_id = fields.IntField(null=True)
    # api_hash = fields.CharField(max_length=50, null=True)
    join_interval = fields.IntField(default=60)
    # TODO: add handlers etc
    growth = fields.IntField(default=5000)
    growth_timerange = fields.IntEnumField(TimeUnit, default=TimeUnit.DAY)
    invites_limit = fields.IntField(default=35)
    invites_reset_after = fields.IntField(default=1)  # days
    recent = fields.BooleanField(default=False)
    enable_proxy = fields.BooleanField(default=True)

    def __str__(self):  # FIXME
        return (f'⚙  Settings\n\n'
                f'Join delay: <code>{self.join_interval}</code> seconds\n'
                f'Session invite limit: <code>{self.invites_limit}</code>\n'
                f'Limit resets after: <code>{self.invites_reset_after}</code> days')

    async def save(self, *args, **kwargs):
        await super().save(*args, **kwargs)
        self._cached = None

    def get_invites_random(self, offset=5):
        low = max(0, self.invites_limit - offset)
        high = min(50, self.invites_limit + offset)
        return random.randint(low, high)

    @classmethod
    async def get_cached(cls):
        if not cls._cached:
            cls._cached = await cls.get()
        return cls._cached


class ApiConfig(Model):
    api_id = fields.IntField()
    hash = fields.CharField(max_length=50)
    active = fields.BooleanField(default=False)

    def __str__(self):
        verified = 'Yes ✅' if self.active else 'No ❌'
        return (f'Api id: <code>{self.api_id}</code>\n'
                f'Api hash: <code>{self.hash}</code>\n'
                f'Verified: {verified}')


# class Proxy(Model):
#     address = fields.CharField(max_length=2048)
#     port = fields.IntField()
#     username = fields.CharField(max_length=128)
#     passwd = fields.CharField(max_length=64)


class Account(Model):
    api_id = fields.IntField()
    api_hash = fields.CharField(max_length=128)
    phone = fields.CharField(max_length=20, unique=True)
    name = fields.CharField(max_length=255)
    session_string = fields.TextField(null=True)
    invites = fields.IntField(null=True)
    invites_ended_at = fields.DatetimeField(null=True)
    # invites_max = fields.IntField(null=True)
    # invites_sent = fields.IntField(default=0)
    # invites_reset_at = fields.DatetimeField(null=True)
    authenticated = fields.BooleanField(default=True)
    deactivated = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    # async def incr_invites(self, num=1):
    #     self.invites_sent += num
    #     await self.save()

    # @property
    # def can_invite(self):
    #     return self.invites_sent < self.invites_max

    # @property
    # def invites_left(self):
    #     return self.invites_max - self.invites_sent

    # async def refresh_invites(self):
    #     if not self.invites:
    #         settings = await Settings.get_cached()
    #         if (self.invites_ended_at + datetime.timedelta(days=settings.invites_timeframe)) <= timezone.now():
    #         reset_at = self.invites_reset_at.replace(tzinfo=None)
    #         if datetime.datetime.now() >= reset_at:
    #             self.invites_sent = 0
    #             await self.save()
    #
    #     if not self.can_invite:
    #         reset_at = self.invites_reset_at.replace(tzinfo=None)
    #         if datetime.datetime.now() >= reset_at:
    #             self.invites_sent = 0
    #             await self.save()

    @property
    def safe_name(self):
        return quote_html(self.name)

    def get_detail_msg(self):
        msg = (f'Name: <b>{self.safe_name}</b>\n'
               f'Phone: <b>{self.phone}</b>\n'
               f'API id: <b>{self.api_id}</b>\n'
               f'API hash: <b>{self.api_hash}</b>\n\n'
               f'Invites left: <b>{self.invites}</b>\n')
        # if not self.can_invite:
        #     msg += '\nInvites reset at: <b>{}</b>'.format(self.invites_reset_at.strftime('%d-%m-%Y %H:%M'))
        # if self.auto_created:
        #     msg += '\n<i>Account was created automatically.</i>'
        # if self.master:
        #     msg = '🎩 Main account\n' + msg
        return msg

    @classmethod
    async def update_invites(cls):
        settings = await Settings.get()
        resets = timezone.now() + datetime.timedelta(days=settings.invites_reset_after)
        await cls.filter(invites=0, invites_ended_at__lte=resets).update(invites=settings.get_invites_random())


class Group(Model):
    name = fields.CharField(max_length=128, null=True)
    link = fields.CharField(max_length=2048)
    enabled = fields.BooleanField(default=True)
    is_target = fields.BooleanField(default=False)
    join_interval = fields.IntField(default=60)

    users_count = fields.IntField(null=True)
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
        modules={'models': ['tg_scraper.models']},
        use_tz=True,
        timezone='UTC'
    )
    await Tortoise.generate_schemas()
    if not await Settings.exists():
        await Settings.create()
