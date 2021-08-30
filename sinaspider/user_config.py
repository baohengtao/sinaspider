from collections import OrderedDict

import pendulum

from sinaspider.helper import logger, pause
from sinaspider.user import User


class UserConfig(OrderedDict):
    from sinaspider.database import config_table as table

    def update_table(self):
        user = User(self['id'])
        self.update(
            nickname=user['screen_name'],
            followers=user['followers_count'],
            following=user['follow_count'],
            birthday=user.get('birthday'),
            homepage=user['homepage'],
            is_following=user['following'],
            age=user.get('age'),
        )
        self.table.upsert(self, ['id'])

    @classmethod
    def from_user_id(cls, user_id):
        user = cls.table.find_one(id=user_id)
        if not user:
            user = cls(
                id=user_id,
                weibo_fetch=False,
                follow_fetch=False,
                weibo_since=pendulum.from_timestamp(0, tz='local'),
                follow_since=pendulum.from_timestamp(0, tz='local')
            )
        else:
            user = cls(user)
        user.update_table()
        return user

    def is_weibo_fetch(self, value=None) -> bool:
        if value is not None:
            assert isinstance(value, bool)
            self['weibo_fetch'] = value
        is_fetch = self.setdefault('weibo_fetch', False)
        self.update_table()
        return is_fetch

    def is_follow_fetch(self, value=None):
        if value is not None:
            assert isinstance(value, bool)
            self['follow_fetch'] = value
        is_fetch = self.setdefault('follow_fetch', False)
        self.update_table()
        return is_fetch

    def weibo_fetch(self, download_dir, days=5):
        if not self.is_weibo_fetch():
            print('skipping....for weibo_fetch is set to False')
            return
        weibo_since, now = pendulum.instance(self['weibo_since']), pendulum.now()
        if weibo_since.diff().days < days:
            print(f'skipping...for fetched at recent {days} days')
            return
        logger.info(f'正在获取用户 {self["screen_name"]} 自 {weibo_since:%y-%m-%d} 起的所有微博')
        user = User(self['id'])
        weibos = user.weibos(retweet=True,
                             since=weibo_since, 
                             download_dir=download_dir)
        print(user)
        for weibo in weibos:
            print(weibo)

        self.update(weibo_since=now, weibo_since_previous=weibo_since)
        self.update_table()
        logger.success(f'{user["screen_name"]}微博获取完毕')
        pause(mode='user')

    def follow_fetch(self, days=None):
        if not self.is_follow_fetch():
            print('skipping....for follow_fetch is set to False')
            return
        days = days or 15
        follow_since, now = pendulum.instance(self['follow_since']), pendulum.now()
        if follow_since.diff().days < days:
            print(f'skipping...for fetched at recent {days} days')
        logger.info(f'正在获取用户 {self["screen_name"]}的关注信息')
        user = User(self['id'])
        print(user)
        list(user.following())
        self.update(follow_since=now)
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
