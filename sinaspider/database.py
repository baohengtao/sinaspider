from sqlalchemy import ARRAY, Text
import dataset

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

# create columns of list type:
user_table.create_column('education', ARRAY(Text))
