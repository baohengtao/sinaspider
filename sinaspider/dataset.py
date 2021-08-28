import dataset

USER_TABLE = 'user'
WEIBO_TABLE = 'weibo'
CONFIG_TABLE = 'config'
RELATION_TABLE = 'relation'

pg = dataset.connect('postgresql://localhost/weibo')
user_table = pg[USER_TABLE]
weibo_table = pg[WEIBO_TABLE]
config_table = pg[CONFIG_TABLE]
relation_table = pg[RELATION_TABLE]
