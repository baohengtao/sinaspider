from collections import UserDict
from pathlib import Path

import pendulum

from sinaspider.helper import logger, pause
from sinaspider.user import User
from sinaspider.config import config



class UserConfig(UserDict):
    from sinaspider.database import config_table as table

    def __init__(self, arg=None, /, **kwargs):
        if isinstance(arg, (int, str)):
            assert not kwargs
            uid = int(arg)
            self.data = self.table.find_one(user_id=uid) or {
                'id': uid,
                'weibo_fetch': False,
                'retweet_fetch': False,
                'media_download': False,
                'relation_fetch': False
            }
            self.id = uid
            self.update_table()
        else:
            super().__init__(arg, **kwargs)
            self.id = self['id']

    def update_table(self):
        if not self.id:
            logger.error(f'no self.id: {self}')
        user = User(self.id)
        if remark := user.pop('remark', ''):
            user['screen_name'] = remark
        self.update(user)
        self.table.upsert(self, ['id'], ensure=True)

    def toggle_weibo_fetch(self, value=None) -> bool:
        if value is not None:
            assert isinstance(value, bool)
            self['weibo_fetch'] = value
        is_fetch = self.setdefault('weibo_fetch', False)
        self.update_table()
        return is_fetch

    def toggle_retweet_fetch(self, value=None):
        if value is not None:
            assert isinstance(value, bool)
            self['retweet_fetch'] = value
        is_fetch = self.setdefault('retweet_fetch', False)
        self.update_table()
        return is_fetch

    def toggle_media_download(self, value=None):
        if value is not None:
            assert isinstance(value, bool)
            self['media_download'] = value
        is_download = self.setdefault('media_download', False)
        self.update_table()
        return is_download

    def toggle_relation_fetch(self, value=None):
        if value is not None:
            assert isinstance(value, bool)
            self['relation_fetch'] = value
        is_fetch = self.setdefault('relation_fetch', False)
        self.update_table()
        return is_fetch

    def toggle_all(self, value):
        self.toggle_weibo_fetch(value)
        self.toggle_retweet_fetch(value)
        self.toggle_media_download(value)
        self.toggle_relation_fetch(value)

    def fetch_weibo(self, download_dir=None, update_interval=5, update=True):
        if not self.toggle_weibo_fetch():
            print(f'skip {self["screen_name"]}...')
            return
        weibo_since, now = self['weibo_update_at'], pendulum.now()
        if weibo_since:
            weibo_since = pendulum.instance(weibo_since)
            if weibo_since.diff().days < update_interval:
                print(
                    f'skipping...for fetched at recent {update_interval} days')
                return
        user = User(self['id'])
        print(user)
        if self.toggle_media_download():
            download_dir = Path(download_dir or config['download_dir'])
            download_dir /= self['screen_name']
        else:
            download_dir = None

        weibos = user.weibos(retweet=self.toggle_retweet_fetch(),
                             since=weibo_since,
                             download_dir=download_dir)
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

    def fetch_relation(self):
        if not self.toggle_relation_fetch():
            return
        logger.info(f'正在获取用户 {self["screen_name"]}的关注信息')
        user = User(self['id'])
        print(user)
        user.relation()
        logger.success(f'{self["screen_name"]} 的关注已获取')

    def __str__(self):
        text = ''
        for k, v in self.items():
            from datetime import datetime
            if isinstance(v, datetime):
                v = v.strftime('%Y-%m-%d %H:%M:%S')
            text += f'{k}: {v}\n'
        return text
