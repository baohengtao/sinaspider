from datetime import datetime
from pathlib import Path
from typing import Optional

import pendulum
from loguru import logger
from peewee import Model
from playhouse.postgres_ext import (
    PostgresqlExtDatabase, IntegerField, BooleanField, TextField,
    BigIntegerField, DateTimeField, BigAutoField,
    ArrayField, CharField, ForeignKeyField, JSONField,
)

from sinaspider.helper import normalize_wb_id, pause
from sinaspider.page import get_weibo_pages
from sinaspider.parser import get_weibo_by_id, get_user_by_id
from sinaspider.thread import ClosableQueue, start_threads, stop_threads

database = PostgresqlExtDatabase(None, autoconnect=True)


def init_database(db_name):
    database.init(db_name)
    database.create_tables([User, UserConfig, Weibo])
    return database


class BaseModel(Model):
    class Meta:
        database = database


class User(BaseModel):
    id = BigIntegerField(primary_key=True, unique=True)
    screen_name = TextField()
    remark = TextField(null=True)
    following = BooleanField()
    birthday = TextField(null=True)
    age = IntegerField(null=True)
    gender = TextField()
    education = ArrayField(field_class=TextField, null=True)
    location = TextField(null=True)

    hometown = TextField(null=True)
    description = TextField(null=True)
    homepage = TextField(null=True)
    statuses_count = IntegerField(null=True)
    followers_count = IntegerField(null=True)
    follow_count = IntegerField(null=True)
    follow_me = BooleanField(null=True)

    avatar_hd = TextField(null=True)
    close_blue_v = BooleanField(null=True)
    like = BooleanField(null=True)
    like_me = BooleanField(null=True)
    mbrank = BigIntegerField(null=True)
    mbtype = BigIntegerField(null=True)
    urank = BigIntegerField(null=True)
    verified = BooleanField(null=True)
    verified_reason = TextField(null=True)
    verified_type = BigIntegerField(null=True)
    verified_type_ext = BigIntegerField(null=True)
    公司 = TextField(null=True)
    工作经历 = TextField(null=True)
    性取向 = TextField(null=True)
    感情状况 = TextField(null=True)
    标签 = TextField(null=True)
    注册时间 = TextField(null=True)
    阳光信用 = TextField(null=True)
    审核时间 = TextField(null=True)
    电话 = TextField(null=True)
    邮箱 = TextField(null=True)

    class Meta:
        table_name = 'user'

    @classmethod
    def from_id(cls, user_id: int, update=False) -> Optional['User']:
        assert isinstance(user_id, int)
        cache_days = 30 if not update else 0
        if (user := User.get_or_none(id=user_id)) is None:
            force_insert = True
            update = True
            user = User()
        else:
            force_insert = False
        if update:
            user_dict = get_user_by_id(user_id, cache_days=cache_days)
            for k, v in user_dict.items():
                setattr(user, k, v)
            user.save(force_insert=force_insert)
        return user

    def timeline(self, start_page=1, since: int | str | datetime = '1970-01-01'):
        weibos = get_weibo_pages(f'107603{self.id}', start_page, since)
        yield from weibos

    def __str__(self):
        text = ''
        keys = ['id', 'screen_name', 'gender', 'birthday', 'location', 'homepage',
                'description', 'statuses_count', 'followers_count', 'follow_count']
        for k in keys:
            if v := getattr(self, k, None):
                text += f'{k}: {v}\n'
        return text


class Weibo(BaseModel):
    id = BigAutoField()
    bid = TextField(null=True)
    user = ForeignKeyField(User, backref='weibos')
    screen_name = TextField(null=True)
    created_at = DateTimeField(null=True)
    text = TextField(null=True)
    url = TextField(null=True)
    url_m = TextField(null=True)
    at_users = ArrayField(field_class=TextField, null=True)
    location = TextField(null=True)
    attitudes_count = IntegerField(null=True)
    comments_count = IntegerField(null=True)
    reposts_count = IntegerField(null=True)
    source = TextField(null=True)
    topics = ArrayField(field_class=TextField, null=True)
    photos = JSONField(null=True)
    video_duration = BigIntegerField(null=True)
    video_url = TextField(null=True)

    class Meta:
        table_name = 'weibo'

    @classmethod
    def from_id(cls, id):

        wb_id = normalize_wb_id(id)
        if not (weibo := Weibo.get_or_none(id=wb_id)):
            weibo_dict = get_weibo_by_id(wb_id)
            weibo = Weibo(**weibo_dict)
            weibo.user = User.from_id(weibo.user_id)
            weibo.save(force_insert=True)
        return weibo

    def medias(self, filepath=None):
        photos = self.photos or {}
        for sn, urls in photos.items():
            for url in filter(bool, urls):
                *_, ext = url.split('/')[-1].split('.')
                if not _:
                    ext = 'jpg'
                yield {
                    'url': url,
                    'filename': f'{self.user_id}_{self.id}_{sn}.{ext}',
                    'xmp_info': self.gen_meta(sn),
                    'filepath': filepath
                }
        if url := self.video_url:
            assert ';' not in url
            if (duration := self.video_duration) and duration > 600:
                logger.warning(f'video_duration is {duration})...skipping...')
            else:
                yield {
                    'url': url,
                    'filename': f'{self.user_id}_{self.id}.mp4',
                    'xmp_info': self.gen_meta(),
                    'filepath': filepath
                }

    def gen_meta(self, sn: str | int = 0) -> dict:
        sn = int(sn) if sn else 0
        xmp_info = {
            'ImageUniqueID': self.bid,
            'ImageSupplierID': self.user_id,
            'ImageSupplierName': 'Weibo',
            'ImageCreatorName': self.screen_name,
            'BlogTitle': self.text,
            'BlogURL': self.url,
            'Location': self.location,
            'DateCreated': self.created_at + pendulum.Duration(microseconds=int(sn)),
            'SeriesNumber': sn
        }

        xmp_info['DateCreated'] = xmp_info['DateCreated'].strftime(
            '%Y:%m:%d %H:%M:%S.%f')
        return {'XMP:' + k: v for k, v in xmp_info.items() if v}

    def __str__(self):
        text = ''
        keys = [
            'user_id', 'screen_name', 'id', 'text', 'location',
            'created_at', 'at_users', 'url'
        ]
        for k in keys:
            if v := getattr(self, k, None):
                text += f'{k}: {v}\n'
        return text


# class Artist(BaseModel):
#     id = ForeignKeyField(column_name='id', field='id',
#                          model=User, primary_key=True)
#     age = IntegerField(index=True, null=True)
#     album = CharField(index=True)
#     description = CharField(index=True, null=True)
#     education = CharField(index=True, null=True)
#     follow_count = IntegerField(index=True)
#     followers_count = IntegerField(index=True)
#     homepage = CharField(index=True, null=True)
#     photos_num = IntegerField(default=0, index=True)
#     recent_num = IntegerField(default=0)
#     statuses_count = IntegerField(index=True)
#     user_name = CharField(index=True)
#
#     class Meta:
#         table_name = 'artist'
#
#
# class Friend(BaseModel):
#     avatar_hd = CharField(index=True)
#     description = CharField(index=True, null=True)
#     friend_id = BigIntegerField(index=True)
#     gender = CharField(index=True)
#     homepage = CharField(index=True)
#     user = ForeignKeyField(column_name='user_id', field='id', model=User)
#
#     class Meta:
#         table_name = 'friend'
#         indexes = (
#             (('user', 'friend_id'), True),
#         )
#         primary_key = CompositeKey('friend_id', 'user')
#

# noinspection PyTypeChecker


class UserConfig(BaseModel):
    user = ForeignKeyField(User)
    screen_name = CharField()
    age = IntegerField(index=True, null=True)
    weibo_fetch = BooleanField(index=True, default=True)
    weibo_update_at = DateTimeField(index=True, default=pendulum.datetime(1970, 1, 1))
    following = BooleanField()
    description = CharField(index=True, null=True)
    education = CharField(index=True, null=True)
    homepage = CharField(index=True)

    class Meta:
        table_name = 'userconfig'

    @classmethod
    def from_id(cls, user_id):
        user = User.from_id(user_id)
        if not (user_config := UserConfig.get_or_none(user=user)):
            user_config = UserConfig(user=user)
        fields = set(cls._meta.fields) - {'id'}
        for k in fields:
            if v := getattr(user, k, None):
                setattr(user_config, k, v)
        user_config.screen_name = user.remark or user.screen_name
        user_config.save()
        return user_config

    def fetch_weibo(self, download_dir,
                    update_interval=0.01, start_page=1):
        if not self.weibo_fetch:
            print(f'skip {self.screen_name}...')
            return
        weibo_since, now = self.weibo_update_at, pendulum.now()
        if pendulum.instance(weibo_since).diff().days < update_interval:
            print(f'skipping...for fetched at recent {update_interval} days')
            return
        User.from_id(self.user_id, update=True)
        print(self.user)

        weibos = self.user.timeline(
            since=weibo_since, start_page=start_page)
        logger.info(
            f'正在获取用户 {self.screen_name} 自 {weibo_since:%y-%m-%d} 起的所有微博')
        logger.info(f"Media Saving: {download_dir}")

        img_queue = ClosableQueue(maxsize=100)
        threads = start_threads(10, img_queue)
        for img in self._save_weibo(weibos, download_dir):
            img_queue.put(img)
        stop_threads(img_queue, threads)
        logger.success(f'{self.user.screen_name}微博获取完毕')
        self.update(weibo_update_at=now).execute()
        pause(mode='user')
        return

    def _save_weibo(self, weibos, download_dir):
        path = Path(download_dir) / self.user.screen_name
        for weibo_dict in weibos:
            wb_id = weibo_dict['id']
            if not (weibo := Weibo.get_or_none(id == wb_id)):
                weibo = Weibo.create(**weibo_dict)
            medias = list(weibo.medias(path))
            print(weibo)
            logger.info(
                f"Downloading {len(medias)} files to {path}...")
            yield from medias
