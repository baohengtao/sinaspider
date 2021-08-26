import pickle

import dataset
import pendulum

from sinaspider.helper import logger, get_json
from sinaspider.user import User
from sinaspider.weibo import Weibo

pg = dataset.connect('postgresql://localhost/weibo')
CONFIG_TABLE = 'config'
RELATION_TABLE = 'relation'
config_table = pg[CONFIG_TABLE]
relation_table = pg[RELATION_TABLE]


def get_favor_pages():
    page = 0
    while True:
        page += 1
        js = get_json(containerid=230259, page=page)
        mblogs = [w['mblog'] for w in js['data']['cards'] if w['card_type'] == 9]
        if not mblogs:
            break
        for weibo_info in mblogs:
            if weibo_info.get('retweeted_status'):
                continue
            weibo = Weibo.from_weibo_info(weibo_info)
            weibo['saved'] = True
            if docu := weibo.docu_in_mongo():
                if docu.get('saved') is True:
                    logger.info(f'{weibo["id"]}已保存, 忽略...')
                    continue
            user_id = weibo['user_id']
            User.from_user_id(user_id)
            yield weibo


def relation_loop():
    _update_config_info()
    config_filter = config_table.find(
        tracing=True,
        tracing_date={'lt': pendulum.now().subtract(days=15)},
        order_by='tracing_date')
    for user_config in config_filter:
        user = User.from_user_id(user_config['id'])
        for followed in user.following():
            if docu := relation_table.find(id=followed['id']):
                followed = docu | followed
            followed.setdefault('follower', {})[user['id']] = user['screen_name']
            relation_table.upsert(followed, ['id'])
        user_config.update(
            tracing_date=pendulum.now(),
        )
        config_table.update(user_config, ['id'])
        logger.success(f'{user["screen_name"]} 的关注已获取')


def _relation_complete():
    for user in relation_table.find():
        offline = True
        text = ['清华', 'PKU', 'THU', '大学']
        if desc := user.get('description'):
            if any(t in desc for t in text):
                offline = False
        user_complete = User.from_user_id(user['id'], offline=offline)
        user |= user_complete or {}
        relation_table.update(user, ['id'])


def weibo_loop(download_dir):
    _update_config_info()
    config_filter = config_table.find(
        downloading=True,
        order_by='since',
        since={'lt': pendulum.now().subtract(days=3)}
    )
    downloaded_list = []
    for user_config in config_filter:
        user = User.from_user_id(user_config['id'])
        user.print()
        """爬取页面"""
        since, now = pendulum.instance(user_config['since']), pendulum.now()
        logger.info(f'正在获取用户 {user["screen_name"]} 自 {since:%y-%m-%d} 起的所有微博')
        for weibo in user.weibos():
            if weibo['created_at'] < since:
                if weibo['is_pinned']:
                    logger.warning(f"发现置顶微博, 跳过...")
                    continue
                else:
                    logger.info(
                        f"the time of wb {weibo[f'created_at']} is beyond {since:%y-%m-%d}...end reached")
                    break
            weibo.print()
            downloaded = weibo.save_media(download_dir=download_dir)
            if downloaded:
                downloaded_list.append(downloaded)
                _check_download_path_uniqueness(downloaded_list)

        """更新用户信息"""
        user_config.update({
            'since_previous': since,
            'since': now,
        })
        config_table.update(user_config, ['id'])
        logger.success(f'{user["screen_name"]}微博获取完毕')


def _update_config_info():
    for user_config in config_table.find():
        user = User.from_user_id(user_config['id'])
        user_config.update(
            nickname=user['screen_name'],
            followers=user['followers_count'],
            following=user['follow_count'],
            birthday=user.get('birthday'),
            homepage=user['homepage'],
            is_following=user['following'],
            age=user.get('age'),
        )
        config_table.upsert(user_config, ['id'])


def _check_download_path_uniqueness(download_list):
    filepath_list = {d['filepath'] for d in download_list}
    url_list = {d['url'] for d in download_list}
    length = len(download_list)
    if len(url_list) != length or len(filepath_list) != length:
        with open('download.list', "wb") as f:
            pickle.dump(download_list, f)
        assert False
