import enum

# from aiogram.utils.markdown import escape_md
from tortoise.models import Model
from tortoise import fields, Tortoise


class Account(Model):

    class Status(enum.IntEnum):
        OK = 0
        INVALID_DETAILS = 1
        PHONE_BANNED = 2
        FLOOD_WAIT = 3

    id = fields.IntField(pk=True)
    api_id = fields.IntField()
    api_hash = fields.CharField(max_length=128)
    phone = fields.CharField(max_length=20, unique=True)
    name = fields.CharField(max_length=255)
    status = fields.IntEnumField(enum_type=Status, default=Status.OK)
    banned_for = fields.IntField(null=True)
    session_string = fields.TextField(null=True)

    async def set_invalid_details(self):
        self.status = self.Status.INVALID_DETAILS
        await self.save()

    async def set_phone_banned(self):
        self.status = self.Status.PHONE_BANNED
        await self.save()

    async def set_flood_wait(self, seconds=None):
        self.status = self.Status.FLOOD_WAIT
        self.banned_for = seconds
        await self.save()

    @property
    def password(self):
        return None

    def __str__(self):
        return '{} {}'.format(self.name, self.phone)

    # def get_label(self, escape_markdown=True):
    #     if escape_markdown:
    #         name = escape_md(self.name)
    #     else:
    #         name = self.name
    #     return '{}   {}'.format(name, self.phone)


async def init_db():
    # Here we create a SQLite DB using file "db.sqlite3"
    #  also specify the app name of "models"
    #  which contain models from "app.models"
    await Tortoise.init(
        db_url='sqlite://db.sqlite3',
        modules={'models': ['tg_scraper.models']}
    )
    # Generate the schema
    await Tortoise.generate_schemas()


# class Run(BaseModel):
#     group_from = peewee.CharField()
#     group_to = peewee.CharField()
#
#
# class ScrapedAccount(BaseModel):
#     run = ForeignKeyField(Run, on_delete='CASCADE', related_name='accounts', null=True)
#     user_id = IntegerField()
