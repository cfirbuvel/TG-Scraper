from peewee import Model, CharField, IntegerField, OperationalError

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


def create_tables(db):
    try:
        db.connect()
    except OperationalError:
        db.close()
        db.connect()

    db.create_tables(
        [
            Account
        ], safe=True
    )
