import dataset
from sqlalchemy import ARRAY, Text, Integer, Boolean, DateTime, JSON, BigInteger
from sqlalchemy_utils import database_exists, create_database

from sinaspider.helper import get_config

USER_TABLE = 'user'
WEIBO_TABLE = 'weibo'
CONFIG_TABLE = 'config'
RELATION_TABLE = 'relation'
ARTIST_TABLE = 'artist'
DATABASE = get_config()['database_name']

database_url = f'postgresql://localhost/{DATABASE}'
if not database_exists(database_url):
    create_database(database_url)
database = dataset.connect(database_url)
_table_para = dict(
    primary_id='id',
    primary_type=BigInteger,
    primary_increment=False)
user_table = database.create_table(USER_TABLE, **_table_para)
weibo_table = database.create_table(WEIBO_TABLE, **_table_para)
config_table = database.create_table(CONFIG_TABLE, **_table_para)
relation_table = database.create_table(RELATION_TABLE)

if get_config().as_bool('write_xmp'):
    artist_table = database.create_table(ARTIST_TABLE, **_table_para)
else:
    artist_table = None


def create_table_columns(table, columns):
    for column_key, column_type in columns:
        table.create_column(column_key, column_type)


user_columns = (
    ('screen_name', Text),
    ('following', Boolean),
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
    ('follow_me', Boolean),
)
create_table_columns(user_table, user_columns)

relation_columns = (
    ('follower', BigInteger),
    ('follower_name', Text),
    ('following', BigInteger),
    ('screen_name', Text),
    ('is_friends', Boolean),
    ('gender', Text),
    ('birthday', Text),
    ('age', Integer),
    ('hometown', Text),
    ('education', ARRAY(Text)),
    ('description', Text),
    ('followers_count', Integer),
    ('follow_count', Integer),
    ('statuses_count', Integer),
    ('homepage', Text),
)
create_table_columns(relation_table, relation_columns)

config_columns = (
    ('screen_name', Text),
    ('age', Integer),
    ('gender', Text),
    ('education', ARRAY(Text)),
    ('weibo_fetch', Boolean),
    ('retweet_fetch', Boolean),
    ('media_download', Boolean),
    ('weibo_update_at', DateTime(timezone=True)),
    ('statuses_count', Integer),
    ('relation_fetch', Boolean),
    ('followers_count', Integer),
    ('follow_count', Integer),
    ('following', Boolean),
    ('follow_update_at', DateTime(timezone=True)),
    ('location', Text),
    ('homepage', Text),
)
create_table_columns(config_table, config_columns)

weibo_columns = (
    ('bid', Text),
    ('user_id', BigInteger),
    ('screen_name', Text),
    ('text', Text),
    ('location', Text),
    ('created_at', DateTime(timezone=True)),
    ('at_users', ARRAY(Text)),
    ('topics', ARRAY(Text)),
    ('source', Text),
    ('original_id', BigInteger),
    ('original_bid', Text),
    ('original_uid', BigInteger),
    ('original_text', Text),
    ('reposts_count', Integer),
    ('comments_count', Integer),
    ('attitudes_count', Integer),
    ('url', Text),
    ('url_m', Text),
    ('photos', JSON),
    ('video_url', Text),
    ('is_pinned', Boolean),
)
create_table_columns(weibo_table, weibo_columns)

if artist_table:
    artist_columns = {
        ('artist', Text),
        ('user_name', Text),
        ('album', Text),
        ('homepage', Text),
        ('following', Boolean),
        ('remark', Text),
        ('birthday', Text),
        ('age', Integer),
        ('gender', Text),
        ('education', ARRAY(Text)),
        ('location', Text),
        ('hometown', Text),
        ('description', Text),
        ('statuses_count', Integer),
        ('followers_count', Integer),
        ('follow_count', Integer),
        ('follow_me', Boolean),
    }
    create_table_columns(artist_table, artist_columns)
