import dataset
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
user_table = pg[USER_TABLE]
weibo_table = pg[WEIBO_TABLE]
config_table = pg[CONFIG_TABLE]
relation_table = pg[RELATION_TABLE]
