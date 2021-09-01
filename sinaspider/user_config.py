from collections import OrderedDict
from pathlib import Path

import pendulum

from sinaspider.helper import logger, pause
from sinaspider.user import User


class UserConfig(OrderedDict):
    from sinaspider.database import config_table as table

    def __init__(self, *args, **kwargs):
        if kwargs or args[1:] or not isinstance(args[0], int):
            super().__init__(*args, **kwargs)
        else:
            super().__init__(self._from_user_id(args[0]))
            self.update_table()

    def update_table(self):
        user = User(self['id'])
        if remark := user.pop('remark'):
            user['screen_name'] = remark
        self.table.upsert(user, ['id'], ensure=False)
        self.table.upsert(self, ['id'], ensure=True)

    @classmethod
    def _from_user_id(cls, user_id):
        init_user = cls(
            id=user_id,
            weibo_fetch=False,
            retweet_fetch=False,
            media_download=False,
            follow_fetch=False,
        )
        user = cls.table.find_one(id=user_id) or init_user
        cls(user).update_table()
        user = cls.table.find_one(id=user_id)
        return cls(user)

    def toggle_weibo_fetch(self, value=None) -> bool:
        if value is not None:
            assert isinstance(value, bool)
            self['weibo_fetch'] = value
        is_fetch = self.setdefault('weibo_fetch', False)
        self.update_table()
        logger.info(f'Fetch Weibo: {is_fetch}')
        return is_fetch

    def toggle_retweet_fetch(self, value=None):
        if value is not None:
            assert isinstance(value, bool)
            self['retweet_fetch'] = value
        is_fetch = self.setdefault('retweet_fetch', False)
        self.update_table()
        logger.info(f'Fetch Retweet: {is_fetch}')
        return is_fetch

    def toggle_media_download(self, value=None):
        if value is not None:
            assert isinstance(value, bool)
            self['media_download'] = value
        is_download = self.setdefault('media_download', False)
        self.update_table()
        logger.info(f'Download Media: {is_download}')
        return is_download

    def toggle_follow_fetch(self, value=None):
        if value is not None:
            assert isinstance(value, bool)
            self['follow_fetch'] = value
        is_fetch = self.setdefault('follow_fetch', False)
        self.update_table()
        logger.info(f'Fetch following: {is_fetch}')
        return is_fetch

    def toggle_all(self, value):
        self.toggle_weibo_fetch(value)
        self.toggle_retweet_fetch(value)
        self.toggle_media_download(value)
        self.toggle_follow_fetch(value)

    def fetch_weibo(self, download_dir=None, update_interval=5, update=True):
        if not self.toggle_weibo_fetch():
            print('skipping....for weibo_fetch is set to False')
            return
        weibo_since, now = self['weibo_update_at'], pendulum.now()
        if weibo_since:
            weibo_since = pendulum.instance(weibo_since)
            if weibo_since.diff().days < update_interval:
                print(f'skipping...for fetched at recent {update_interval} days')
                return
        user = User(self['id'])
        if self.toggle_media_download():
            if download_dir:
                download_dir = Path(download_dir) / self['screen_name']
            else:
                download_dir = Path.home() / 'Downloads/sinaspider' / self['screen_name']
        else:
            download_dir = None

        weibos = user.weibos(retweet=self.toggle_retweet_fetch(),
                             since=weibo_since,
                             download_dir=download_dir)
        print(user)
        logger.info(
            f'正在获取用户 {self["screen_name"]} 自 {weibo_since:%y-%m-%d} 起的所有微博')
        logger.info(f"Fetching Retweet: {self.toggle_retweet_fetch()}")
        logger.info(f"Media Saving: {download_dir or False}")
        logger.info(f"Update Config: {update}")
        for weibo in weibos:
            print(weibo)
        if update:
            self.update(weibo_update_at=now, weibo_previous_update=weibo_since)
            self.update_table()
        logger.success(f'{user["screen_name"]}微博获取完毕')
        pause(mode='user')

    def fetch_follow(self, days=None):
        if not self.toggle_follow_fetch():
            print('skipping....for follow_fetch is set to False')
            return
        days = days or 15
        follow_update_at = self['follow_update_at']
        if follow_update_at:
            follow_update_at = pendulum.instance(follow_update_at)
            if follow_update_at.diff().days < days:
                print(f'skipping...for fetched at recent {days} days')
        logger.info(f'正在获取用户 {self["screen_name"]}的关注信息')
        user = User(self['id'])
        print(user)
        user.following()
        self.update(follow_update_at=pendulum.now())
        self.update_table()
        logger.success(f'{user["screen_name"]} 的关注已获取')
        pause(mode='user')

    @classmethod
    def yield_config_user(cls, **params):
        """
        :param params:
            传递给table.find的参数, 例如:
                downloading=True,
                order_by='weibo_since',
                weibo_since={'lt': pendulum.now().subtract(days=days)}
        :return:
        """
        for user in cls.table.find(**params):
            user = {k: v for k, v in user.items() if v is not None}
            yield cls(user)

    def __str__(self):
        text = ''
        for k, v in self.items():
            from datetime import datetime
            if isinstance(v, datetime):
                v = v.strftime('%Y-%m-%d %H:%M:%S')
            text += f'{k}: {v}\n'
        return text


def _relation_complete():
    for user in User.relation_table.find():
        offline = True
        text = ['清华', 'PKU', 'THU', '大学']
        if desc := user.get('description'):
            if any(t in desc for t in text):
                offline = False
        user_complete = User.from_user_id(user['id'], offline=offline)
        user |= user_complete or {}
        User.relation_table.update(user, ['id'])
