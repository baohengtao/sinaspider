import dataset
from sqlalchemy import ARRAY, Text
import keyring
import os
from sinaspider.helper import logger

USER_TABLE = 'user'
WEIBO_TABLE = 'weibo'
CONFIG_TABLE = 'config'
RELATION_TABLE = 'relation'
db_default='sina'
if db:=os.environ.get('SINA_SPIDER_DATABASE'):
    logger.info(f'use database: {db} (set by env SINA_SPIDER_DATABASE)')
elif db:=keyring.get_password('sinaspider', 'database'):
    logger.info(f'use database: {db} (set by keyring)')
else:
    logger.info(f'database not set. use default({db_default})')
DATABASE = db or db_default
    


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