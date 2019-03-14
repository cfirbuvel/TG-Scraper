from peewee import Model, CharField, IntegerField, OperationalError, ForeignKeyField

from bot_helpers import init_db

db = init_db('config.ini')


class BaseModel(Model):

    class Meta:
        database = db


class Account(BaseModel):
    api_id = IntegerField()
    api_hash = CharField(max_length=255)
    phone = CharField(max_length=255)
    username = CharField(max_length=255, null=True, default=None)


class Run(BaseModel):
    run_hash = CharField()
    group_from = IntegerField(null=True)
    group_to = IntegerField(null=True)


class ScrapedAccount(BaseModel):
    run = ForeignKeyField(Run, on_delete='CASCADE', related_name='accounts', null=True)
    user_id = IntegerField()


def create_tables(db):
    try:
        db.connect()
    except OperationalError:
        db.close()
        db.connect()

    db.create_tables(
        [
            Account,
            Run,
            ScrapedAccount,

        ], safe=True
    )
