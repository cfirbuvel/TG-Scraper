import os
from playhouse.migrate import SqliteDatabase, SqliteMigrator, migrate, CharField

if __name__ == '__main__':
    d = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(d, "'db.sqlite'")
    db = SqliteDatabase(db_path)
    migrator = SqliteMigrator(db)
    group_from = CharField(default='')
    group_to = CharField(default='')

    migrate(
        migrator.drop_column('run', 'run_hash'),
        migrator.drop_column('run', 'group_from'),
        migrator.drop_column('run', 'group_to'),
        migrator.add_column('run', 'group_from', group_from),
        migrator.add_column('run', 'group_to', group_to)
    )
    db.close()



