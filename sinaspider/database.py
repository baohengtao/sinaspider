import dataset
from sqlalchemy import ARRAY, Text, Integer, Boolean, DateTime

from sinaspider.helper import config

USER_TABLE = 'user'
WEIBO_TABLE = 'weibo'
CONFIG_TABLE = 'config'
RELATION_TABLE = 'relation'
DATABASE = config()['database_name']

pg = dataset.connect(f'postgresql://localhost/{DATABASE}')
_table_para = dict(
    primary_id='id',
    primary_type=pg.types.bigint,
    primary_increment=False)
user_table = pg.create_table(USER_TABLE, **_table_para)
weibo_table = pg.create_table(WEIBO_TABLE, **_table_para)
config_table = pg.create_table(CONFIG_TABLE, **_table_para)
relation_table = pg.create_table(RELATION_TABLE, **_table_para)

user_columns = (
    ('screen_name', Text),
    ('remark', Text),
    ('birthday', Text),
    ('age', Integer),
    ('gender', Text),
    ('education', ARRAY(Text)),
    ('location', Text),
    ('hometown', Text),
    ('description', Text),
    ('homepage', Text),
    ('statuses_count', Integer),
    ('followers_count', Integer),
    ('follow_count', Integer),
    ('following', Boolean),
    ('follow_me', Boolean),
)

config_columns = (
    ('screen_name', Text),
    ('remark', Text),
    ('age', Integer),
    ('gender', Text),
    ('education', ARRAY(Text)),
    ('location', Text),
    ('weibo_fetch', Boolean),
    ('retweet_fetch', Boolean),
    ('media_download', Boolean),
    ('follow_fetch', Boolean),
    ('homepage', Text),
    ('statuses_count', Integer),
    ('followers_count', Integer),
    ('follow_count', Integer),
    ('following', Boolean),
    ('weibo_since', DateTime(timezone=True)),
    ('follow_update', DateTime(timezone=True))
)

for column_key, column_type in user_columns:
    user_table.create_column(column_key, column_type)

for column_key, column_type in config_columns:
    config_table.create_column(column_key, column_type)
