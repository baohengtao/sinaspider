import pendulum

from sinaspider.dataset import config_table, relation_table
from sinaspider.helper import logger, pause
from sinaspider.user import User


class UserConfig(dict):
    table = config_table

    def update_info(self, update):
        self.table.upsert(self | update, ['id'])

    @classmethod
    def downloading_list(cls, days=3):
        config_filter = cls.table.find(
            downloading=True,
            order_by='since',
            since={'lt': pendulum.now().subtract(days=days)}
        )
        for user in config_filter:
            yield cls(user)

    @classmethod
    def tracing_list(cls, days=30):
        config_filter = cls.table.find(
            tracing=True,
            order_by='tracing_date',
            tracing_date={'lt': pendulum.now().subtract(days=days)}
        )
        for user in config_filter:
            yield cls(user)

    @classmethod
    def update_config_info(cls):
        for user_config in cls.table.find():
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


def weibo_loop(download_dir):
    UserConfig.update_config_info()

    downloaded_list = []
    for user_config in UserConfig.downloading_list(days=3):
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
            downloaded = weibo.save_media(download_dir=download_dir, write_xmp=True)
            if downloaded:
                downloaded_list.extend(downloaded)
                _check_download_path_uniqueness(downloaded_list)

        """更新用户信息"""
        user_config.update_info({
            'since_previous': since,
            'since': now,
        })
        logger.success(f'{user["screen_name"]}微博获取完毕')
        pause(mode='user')


def relation_loop():
    UserConfig.update_config_info()
    for user_config in UserConfig.tracing_list(days=30):
        user = User.from_user_id(user_config['id'])
        for followed in user.following():
            if followed['gender'] != 'female':
                pass
            if docu := relation_table.find(id=followed['id']):
                followed = docu | followed
            followed.setdefault('follower', {})[user['id']] = user['screen_name']
            relation_table.upsert(followed, ['id'])
        user_config.update_info({'tracing_date': pendulum.now()})
        logger.success(f'{user["screen_name"]} 的关注已获取')
        pause(mode='user')
    _relation_complete()


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


def _check_download_path_uniqueness(download_list):
    filepath_list = {d['filepath'] for d in download_list}
    url_list = {d['url'] for d in download_list}
    length = len(download_list)
    if len(url_list) != length or len(filepath_list) != length:
        with open('download.list', "wb") as f:
            import pickle
            pickle.dump(download_list, f)
        assert False
