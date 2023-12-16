import pickle
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterator, Self
from urllib.parse import parse_qs, urlparse

import pendulum
from geopy.distance import geodesic
from peewee import Model
from playhouse.postgres_ext import (
    ArrayField,
    BigIntegerField,
    BooleanField, CharField,
    DateTimeTZField,
    DeferredForeignKey,
    DoubleField,
    ForeignKeyField,
    IntegerField,
    PostgresqlExtDatabase,
    TextField
)
from playhouse.shortcuts import model_to_dict

from sinaspider import console
from sinaspider.exceptions import WeiboNotFoundError
from sinaspider.helper import (
    download_files, fetcher,
    normalize_wb_id,
    parse_loc_src,
    parse_url_extension,
    round_loc
)
from sinaspider.page import Page
from sinaspider.parser import UserParser, WeiboParser

database = PostgresqlExtDatabase("sinaspider", host="localhost")


class BaseModel(Model):
    class Meta:
        database = database

    def __str__(self):
        model = model_to_dict(self, recurse=False)
        for k, v in model.items():
            if isinstance(v, datetime):
                model[k] = v.strftime("%Y-%m-%d %H:%M:%S")

        return "\n".join(f'{k}: {v}' for k, v in model.items()
                         if v is not None)

    @classmethod
    def get_or_none(cls, *query, **filters) -> Self | None:
        return super().get_or_none(*query, **filters)

    @classmethod
    def get(cls, *query, **filters) -> Self:
        return super().get(*query, **filters)

    @classmethod
    def get_by_id(cls, *query, **filters) -> Self:
        return super().get_by_id(*query, **filters)


class UserConfig(BaseModel):
    user: "User" = DeferredForeignKey("User", unique=True, backref='config')
    username = CharField()
    nickname = CharField(null=True)
    age = IntegerField(null=True)
    weibo_fetch = BooleanField(default=False)
    weibo_fetch_at = DateTimeTZField(null=True)
    weibo_next_fetch = DateTimeTZField(null=True)
    liked_fetch = BooleanField(default=False)
    liked_fetch_at = DateTimeTZField(null=True)
    liked_next_fetch = DateTimeTZField(null=True)
    post_at = DateTimeTZField(null=True)
    following = BooleanField(null=True)
    description = CharField(null=True)
    education = ArrayField(field_class=TextField, null=True)
    homepage = CharField()
    visible = BooleanField(null=True)
    photos_num = IntegerField(null=True)
    followed_by = ArrayField(field_class=TextField, null=True)
    IP = TextField(null=True)
    folder = TextField(null=True)
    is_friend = BooleanField(default=False)
    bilateral = ArrayField(field_class=TextField, null=True)
    blocked = BooleanField(default=False)

    class Meta:
        table_name = "userconfig"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.page = Page(self.user_id)
        self._liked_list: list[dict] = []

    @classmethod
    def from_id(cls, user_id: int) -> Self:
        user = User.from_id(user_id, update=True)
        user_dict = model_to_dict(user)
        user_dict['user_id'] = user_dict.pop('id')
        to_insert = {k: v for k, v in user_dict.items()
                     if k in cls._meta.columns}
        if cls.get_or_none(user_id=user_id):
            cls.update(to_insert).where(cls.user_id == user_id).execute()
        else:
            cls.insert(to_insert).execute()
        return cls.get(user_id=user_id)

    def set_visibility(self) -> bool:
        if self.weibo_fetch_at is None:
            self.visible = None
        if self.visible is True:
            return True
        visible = self.page.get_visibility()
        if self.visible is None or visible is False:
            self.visible = visible
            self.save()
        else:
            raise ValueError(
                f"conflict: {self.username}当前微博全部可见，请检查")
        if not visible:
            console.log(f"{self.username} 只显示半年内的微博", style="notice")
        return visible

    def fetch_weibo(self, download_dir: Path):
        fetcher.toggle_art(self.following)
        self.fetch_friends()
        if not self.weibo_fetch:
            return
        if self.weibo_fetch_at:
            since = pendulum.instance(self.weibo_fetch_at)
        else:
            since = pendulum.from_timestamp(0)
        msg = f"fetch_at:{since:%y-%m-%d} liked_fetch:"
        if self.liked_fetch_at:
            msg += f" {self.liked_fetch_at:%y-%m-%d}"
        else:
            msg += f" {self.liked_fetch}"
        console.rule(f"开始获取 {self.username} 的主页 ({msg})")
        console.log(self.user)
        console.log(f"Media Saving: {download_dir}")
        self.set_visibility()
        # if not self.set_visibility():
        #     console.log(f"{self.username} 只显示半年内的微博", style="notice")

        now = pendulum.now()
        imgs = self._save_weibo(since, download_dir)
        download_files(imgs)
        console.log(f"{self.username}微博获取完毕\n")

        self.weibo_fetch_at = now
        self.weibo_next_fetch = self.get_weibo_next_fetch()
        if weibos := self.user.weibos.order_by(Weibo.created_at.desc()):
            self.post_at = weibos[0].created_at
        self.save()

    def _save_weibo(
            self,
            since: pendulum.DateTime,
            download_dir: Path) -> Iterator[dict]:
        """
        Save weibo to database and return media info
        :return: generator of medias to downloads
        """

        if since < pendulum.now().subtract(years=1):
            user_root = 'User'
        elif not self.photos_num:
            console.log(
                f'seems {self.username} not processed, using User folder',
                style='green on dark_green')
            user_root = 'User'
        else:
            user_root = 'Timeline'
        download_dir = download_dir / user_root / self.username

        console.log(f'fetch weibo from {since:%Y-%m-%d}\n')
        for weibo_dict in self.page.homepage():
            is_pinned = weibo_dict.pop('is_pinned', False)
            if (created_at := weibo_dict['created_at']) < since:
                if is_pinned:
                    console.log("略过置顶微博...")
                    continue
                else:
                    console.log(
                        f"时间 {created_at:%y-%m-%d} 在 {since:%y-%m-%d}之前, "
                        "获取完毕")
                    return
            weibo_dict['username'] = self.username
            weibo_id = Weibo.upsert(weibo_dict)
            weibo: Weibo = Weibo.get_by_id(weibo_id)
            if weibo.location:
                assert weibo.latitude
            medias = list(weibo.medias(download_dir))
            console.log(weibo)
            for target in ['ins', 'ig']:
                if target in (weibo.text or '').replace('night', '').lower():
                    console.log('🍬 Find Instagram info',
                                style='bold green on dark_green')
                    break
            if medias:
                console.log(
                    f"Downloading {len(medias)} files to {download_dir}..")
            console.print()
            yield from medias

    def fetch_liked(self, download_dir: Path):
        if not self.liked_fetch:
            return
        self.fetch_friends(update=True)
        # update = False

        msg = f"开始获取 {self.username} 的赞"
        if self.liked_fetch_at:
            msg += f" (fetch at:{self.liked_fetch_at:%y-%m-%d})"
        else:
            msg = f"🎈 {msg} (New user) 🎈"
        console.rule(msg, style="magenta")
        console.log(self.user)
        console.log(f"Media Saving: {download_dir}")
        imgs = self._save_liked(download_dir)
        download_files(imgs)

        if count := len(self._liked_list):
            for w in WeiboLiked.select().where(
                    WeiboLiked.user == self.user).order_by(
                    WeiboLiked.order_num.desc()):
                w.order_num += count
                w.save()
            WeiboLiked.insert_many(self._liked_list).execute()
            pic_counts = sum(p['pic_num'] for p in self._liked_list)
            console.log(f"🎀 插入 {count} 条新赞, 共 {pic_counts} 张图片",
                        style="bold green on dark_green")
            WeiboLiked.delete().where(WeiboLiked.order_num > 1000).execute()
            self._liked_list.clear()

        console.log(f"{self.user.username}的赞获取完毕\n")
        self.liked_fetch_at = pendulum.now()
        self.liked_next_fetch = self.get_liked_next_fetch()
        self.save()

    def fetch_friends(self, update=False):
        fids = {f.friend_id for f in self.user.friends}
        if update:
            Friend.delete().where(Friend.user_id == self.user_id).execute()
        if not Friend.get_or_none(user_id=self.user_id):
            console.log(f"开始获取 {self.username} 的好友")
            friends = list(self.page.friends())
            for friend in friends:
                friend['username'] = self.username
            friends = {f['friend_id']: f for f in friends}.values()
            console.log(f'{len(friends)} friends found! 🥰 ')
            Friend.insert_many(friends).execute()
            Friend.delete().where(Friend.gender == 'm').execute()
            Friend.update_frequency()
        fids_updated = {f.friend_id for f in self.user.friends}
        if deleted := (fids-fids_updated):
            console.log('following user be deleted')
            for fid in deleted:
                console.log(f'https://weibo.com/u/{fid}')
        if added := (fids_updated-fids):
            console.log('following user be deleted')
            for fid in added:
                console.log(f'https://weibo.com/u/{fid}')

        self.update_friends()

    def update_friends(self):
        fids = {f.friend_id for f in self.user.friends}
        query = (UserConfig.select()
                 .where(UserConfig.user_id.in_(fids))
                 .where(UserConfig.weibo_fetch)
                 .where(UserConfig.weibo_fetch_at.is_null(False))
                 )
        bilateral_gold = sorted(u.username for u in query)
        if (bilateral := self.user.bilateral or []) != bilateral_gold:
            console.log(f'changing {self.username} bilateral')
            if to_add := (set(bilateral_gold) - set(bilateral)):
                console.log(f'+bilateral: {to_add}',
                            style='green bold on dark_green')
            if to_del := (set(bilateral)-set(bilateral_gold)):
                console.log(f'-bilateral: {to_del}',
                            style='red bold on dark_red')
            console.log(f'bilateral={bilateral_gold}')
            bilateral_gold = bilateral_gold or None
            self.user.bilateral = bilateral_gold
            self.user.save()
            self.bilateral = bilateral_gold
            self.save()

    def _save_liked(self,
                    download_dir: Path,
                    ) -> Iterator[dict]:
        assert Friend.get_or_none(user_id=self.user_id)
        if self.liked_fetch_at:
            folder = f'{self.username}_{self.liked_fetch_at:%y-%m-%d}'
            download_dir /= f"Liked/{folder}"
        else:
            download_dir /= f"Liked_New/{self.username}"
        bulk = []
        early_stopping = False
        for mblog in self.page.liked():
            uid, wid = mblog['user']['id'], int(mblog['id'])
            if not Friend.get_or_none(
                    friend_id=uid,
                    user_id=self.user_id):
                continue
            config = UserConfig.get_or_none(user_id=uid)
            if config and config.weibo_fetch:
                continue
            filepath = download_dir / 'saved' if config else download_dir

            if liked := WeiboLiked.get_or_none(
                    weibo_id=wid, user_id=self.user_id):
                console.log(
                    f'{wid}: early stopped by WeiboLiked'
                    f'with order_num {liked.order_num}',
                    style='warning')
                early_stopping = True
                break
            weibo_dict = WeiboParser(mblog).parse()
            weibo: Weibo = Weibo(**weibo_dict)
            prefix = f"{self.username}_{weibo.username}_{weibo.id}"
            photos = (weibo.photos or []) + (weibo.photos_edited or [])
            console.log(weibo)
            console.log(
                f"Downloading {len(photos)} files to {download_dir}..\n")
            for sn, url in enumerate(photos, start=1):
                url = url.split('🎀')[0]
                assert (ext := parse_url_extension(url))
                xmp_info = weibo.gen_meta(sn, url=url)
                description = '\n'.join([
                    f'weibo.com/{weibo.user_id}/{weibo.bid}',
                    f'weibo.com/u/{weibo.user_id}'
                ])
                marker_note = model_to_dict(weibo, recurse=False)
                marker_note['created_at'] = weibo.created_at.timestamp()
                xmp_info.update({
                    'XMP:Title': f'{weibo.username}⭐️{self.username}',
                    'XMP:Description': description,
                    'XMP:Artist': weibo.username,
                    'XMP:ImageSupplierName': 'WeiboLiked',
                    'XMP:MakerNote': marker_note
                })
                xmp_info["File:FileCreateDate"] = xmp_info['XMP:DateCreated']

                yield {
                    "url": url,
                    "filename": f"{prefix}_{sn}{ext}",
                    "xmp_info": xmp_info,
                    "filepath": filepath
                }
            bulk.append(weibo)
        if early_stopping and not self.liked_fetch_at:
            console.log(
                'early stopping but liked_fetch_at is not set', style='error')
        elif not early_stopping and self.liked_fetch_at:
            console.log(
                'liked_fetch_at is set but not early stopping', style='error')

        assert self._liked_list == []

        for i, weibo in enumerate(bulk, start=1):
            self._liked_list.append({
                'weibo_id': weibo.id,
                'weibo_by': weibo.user_id,
                'pic_num': weibo.pic_num,
                'user_id': self.user_id,
                'username': self.username,
                'created_at': weibo.created_at,
                'order_num': i
            })

    def get_liked_next_fetch(self) -> pendulum.DateTime | None:
        if not self.liked_fetch:
            return
        if self.liked_fetch_at is None:
            return
        liked_fetch_at = pendulum.instance(self.liked_fetch_at)
        query = (WeiboLiked.select()
                 .where(WeiboLiked.user == self.user)
                 .order_by(WeiboLiked.created_at.desc())
                 )
        if not query:
            return liked_fetch_at.add(months=6)
        count = 0
        for liked in query:
            count += liked.pic_num
            if count > 200:
                break
        duration = (liked_fetch_at - liked.created_at) * 200 / count
        days = min(duration.in_days(), 180)
        return liked_fetch_at.add(days=days)

    def get_weibo_next_fetch(self) -> pendulum.DateTime:
        if not self.weibo_fetch:
            return
        if not self.weibo_fetch_at:
            return
        if self.blocked:
            return
        weibo_fetch_at = pendulum.instance(self.weibo_fetch_at)

        if self.post_at:
            interval = (self.weibo_fetch_at - self.post_at).days
            interval = min(max(7, interval), 30)
        else:
            interval = 30
        if not self.is_friend and not self.following:
            interval = min(interval, 2)
        return weibo_fetch_at.add(days=interval)


class User(BaseModel):
    id = BigIntegerField(primary_key=True, unique=True)
    username = TextField()
    nickname = TextField()
    following = BooleanField()
    birthday = TextField(null=True)
    age = IntegerField(null=True)
    gender = TextField()
    education = ArrayField(field_class=TextField, null=True)
    followed_by = ArrayField(field_class=TextField, null=True)
    bilateral = ArrayField(field_class=TextField, null=True)

    description = TextField(null=True)
    homepage = TextField(null=True)
    statuses_count = IntegerField(null=True)
    followers_count = IntegerField(null=True)
    follow_count = IntegerField(null=True)
    follow_me = BooleanField(null=True)
    hometown = TextField(null=True)
    location = TextField(null=True)
    IP = TextField(null=True)

    avatar_hd = TextField(null=True)
    like = BooleanField(null=True)
    like_me = BooleanField(null=True)
    mbrank = BigIntegerField(null=True)
    mbtype = BigIntegerField(null=True)
    urank = BigIntegerField(null=True)
    verified = BooleanField(null=True)
    verified_reason = TextField(null=True)
    verified_type = BigIntegerField(null=True)
    verified_type_ext = BigIntegerField(null=True)
    svip = IntegerField(null=True)
    公司 = TextField(null=True)
    工作经历 = ArrayField(field_class=TextField, null=True)
    感情状况 = TextField(null=True)
    注册时间 = TextField(null=True)
    阳光信用 = TextField(null=True)
    friendships_relation = IntegerField(null=True)
    redirect = BigIntegerField(null=True)

    def __repr__(self):
        return super().__repr__()

    class Meta:
        table_name = "user"

    @classmethod
    def from_id(cls, user_id: int, update=False) -> Self:
        if update or not cls.get_or_none(id=user_id):
            user_dict = UserParser(user_id).parse()
            if followed_by := user_dict.pop('followed_by', None):
                if query := cls.select().where(cls.id.in_(followed_by)):
                    user_dict['followed_by'] = sorted(
                        u.username for u in query)
            cls.upsert(user_dict)
        return cls.get_by_id(user_id)

    @classmethod
    def upsert(cls, user_dict):
        user_id = user_dict['id']
        if not (model := cls.get_or_none(id=user_id)):
            if 'username' not in user_dict:
                user_dict['username'] = user_dict['nickname'].strip('-_ ')
                assert user_dict['username']
            if birth := user_dict.get('birthday'):
                user_dict['age'] = pendulum.parse(birth).diff().in_years()
            return cls.insert(user_dict).execute()
        model_dict = model_to_dict(model)
        if edu := user_dict.pop('education', []):
            for s in model_dict.get('education', []):
                if s not in edu:
                    edu.append(s)
            user_dict['education'] = edu

        if birth := user_dict.pop('birthday', None):
            if not model.birthday or model.birthday >= birth:
                user_dict['birthday'] = birth
                user_dict['age'] = pendulum.parse(birth).diff().in_years()
            else:
                console.log(f'ignore {birth}', style='warning')

        for k, v in user_dict.items():
            if 'count' in k:
                continue
            assert v or v == 0
            if v == model_dict[k]:
                continue
            console.log(f'+{k}: {v}', style='green bold on dark_green')
            if (ori := model_dict[k]) is not None:
                console.log(f'-{k}: {ori}', style='red bold on dark_red')
        return cls.update(user_dict).where(cls.id == user_id).execute()

    def __str__(self):
        keys = ['avatar_hd', 'like', 'like_me', 'mbrank', 'mbtype', 'urank',
                'verified', 'verified_reason', 'verified_type',
                'verified_type_ext', 'svip', '公司', '工作经历',
                '性取向', '感情状况', '标签', '注册时间', '阳光信用']
        model = model_to_dict(self)
        return "\n".join(f"{k}: {v}" for k, v in model.items()
                         if v is not None and k not in keys)


class Weibo(BaseModel):
    id = BigIntegerField(primary_key=True, unique=True)
    bid = TextField(unique=True)
    user = ForeignKeyField(User, backref="weibos")
    username = TextField()
    created_at = DateTimeTZField()
    text = TextField(null=True)
    url = TextField()
    url_m = TextField()
    at_users = ArrayField(field_class=TextField, null=True)
    location = TextField(null=True)
    location_id = TextField(null=True)
    attitudes_count = IntegerField(null=True)
    comments_count = IntegerField(null=True)
    reposts_count = IntegerField(null=True)
    source = TextField(null=True)
    topics = ArrayField(field_class=TextField, null=True)
    video_duration = BigIntegerField(null=True)
    video_url = TextField(null=True)
    photos = ArrayField(field_class=TextField, null=True)
    photos_edited = ArrayField(field_class=TextField, null=True)
    photos_extra = ArrayField(field_class=TextField, null=True)
    pic_num = IntegerField()
    edit_count = IntegerField(null=True)
    edit_at = DateTimeTZField(null=True)
    has_media = BooleanField()
    region_name = TextField(null=True)
    update_status = TextField(null=True)
    latitude = DoubleField(null=True)
    longitude = DoubleField(null=True)
    mblog_from = TextField()
    added_at = DateTimeTZField(null=True)
    updated_at = DateTimeTZField(null=True)
    try_update_at = DateTimeTZField(null=True)
    try_update_msg = TextField(null=True)

    class Meta:
        table_name = "weibo"

    @classmethod
    def from_id(cls, wb_id: int | str, update: bool = False) -> Self:
        wb_id = normalize_wb_id(wb_id)
        if update or not cls.get_or_none(id=wb_id):
            try:
                weibo_dict = WeiboParser(wb_id).parse()
            except WeiboNotFoundError as e:
                if not cls.get_or_none(id=wb_id):
                    raise e
                console.log(
                    f'{e}: Weibo {wb_id} is not accessible, '
                    'loading from database...',
                    style="error")
            else:
                Weibo.upsert(weibo_dict)
        return cls.get_by_id(wb_id)

    @classmethod
    def upsert(cls, weibo_dict: dict) -> int:
        """
        return upserted weibo id
        """
        wid = weibo_dict['id']
        weibo_dict['username'] = User.get_by_id(
            weibo_dict['user_id']).username
        locations = weibo_dict.pop('locations', None)
        regions = weibo_dict.pop('regions', None)
        if weibo_dict['pic_num'] > 0:
            assert weibo_dict.get('photos') or weibo_dict.get('photos_edited')
        if location_src := weibo_dict.pop('location_src', None):
            assert 'location_id' not in weibo_dict
            lid = cls._get_location_id_from_src(location_src)
            weibo_dict['location_id'] = lid

        assert 'updated_at' not in weibo_dict
        assert 'added_at' not in weibo_dict
        if not (model := cls.get_or_none(id=wid)):
            weibo_dict['added_at'] = pendulum.now()
            cls.insert(weibo_dict).execute()
            Weibo.get_by_id(wid).update_location()
            return wid
        else:
            weibo_dict['updated_at'] = pendulum.now()
        if model.location is None:
            assert locations[0] is None
        else:
            assert model.location_id == weibo_dict['location_id']
        assert model.region_name == weibo_dict.get('region_name')

        model_dict = model_to_dict(model, recurse=False)
        model_dict['user_id'] = model_dict.pop('user')

        # compare photos
        if model.update_status == 'updated':
            assert model.photos == weibo_dict.get('photos')
            edited = model.photos_edited or []
            edited_update = weibo_dict.get('photos_edited', [])
            assert edited_update[:len(edited)] == edited
            extra = edited_update[len(edited):]
        else:
            assert not model.photos_edited
            extra = weibo_dict.get('photos', []) + \
                weibo_dict.get('photos_edited', [])
            for p in (model.photos or []):
                p = (p.replace("livephoto.us.sinaimg.cn", "us.sinaimg.cn")
                     .replace('livephoto=//us.sinaimg.cn/',
                              'livephoto=https%3A%2F%2Fus.sinaimg.cn%2F'))
                if p not in extra:
                    # p: model_dict
                    # e: weibo_dict
                    p1, p2 = p.split('🎀')
                    e, *_ = [e for e in extra if e.startswith(p1)]
                    assert not _
                    e1, e2 = e.split('🎀')
                    assert p1 == e1
                    p2, e2 = urlparse(p2), urlparse(e2)
                    assert p2.netloc == e2.netloc == 'g.us.sinaimg.cn'
                    assert p2.path.removesuffix(
                        '.mp4') == e2.path.removesuffix('.mp4')
                    qs1 = parse_qs(p2.query)
                    qs2 = parse_qs(e2.query)
                    for k in ['ssig', 'Expires']:
                        qs1.pop(k)
                        qs2.pop(k)
                    assert set(qs1.keys()) == set(qs2.keys())
                    assert set(qs1.keys()).issubset(
                        {'label', 'template', 'KID'})
                    assert qs1 == qs2
                    assert p2.params == e2.params == ''
                    extra.remove(e)
                else:
                    extra.remove(p)
        if extra:
            assert not model.photos_extra
            assert 'photos_extra' not in weibo_dict
            weibo_dict['photos_extra'] = extra
        # compare other key

        for k, v in weibo_dict.items():
            assert v or v == 0
            if v == model_dict[k]:
                continue
            if k in ['photos', 'photos_edited']:
                continue
            console.log(f'+{k}: {v}', style='green')
            if (ori := model_dict[k]) is not None:
                console.log(f'-{k}: {ori}', style='red')
        if model.try_update_at:
            weibo_dict['try_update_at'] = None
            weibo_dict['try_update_msg'] = None
            console.log(f'-try_update_at: {model.try_update_at}', style='red')
            console.log(
                f'-try_update_msg: {model.try_update_msg}', style='red')

        cls.update(weibo_dict).where(cls.id == wid).execute()
        weibo = Weibo.get_by_id(wid)
        if weibo.has_media:
            assert list(weibo.medias())
            weibo.update_location()
            loc_info = [weibo.location, weibo.location_id,
                        weibo.latitude, weibo.longitude]
            if not all(loc_info):
                assert loc_info == [None] * 4
        else:
            assert not list(weibo.medias())

        return wid

    def update_location(self):
        if self.location is None:
            assert self.location_id is None
            return
        coord = self.get_coordinate()
        if location := Location.from_id(self.location_id):
            if location.name != self.location:
                if location.name:
                    console.log(
                        'location name changed from'
                        f'{location.name} to {self.location}',
                        style='warning')
                location.name = self.location
                location.save()
            console.log(location)
        else:
            assert coord
            console.log(self)
        if coord and location:
            if (err := geodesic(coord, location.coordinate).meters) > 1:
                console.log(
                    f'the distance between coord and location is {err}m',
                    style='notice')
        console.log()
        lat, lng = coord or location.coordinate
        if self.latitude == lat and self.longitude == lng:
            return
        if self.latitude:
            console.log(f'-latitude: {self.latitude}', style='red')
            console.log(f'-longitude: {self.longitude}', style='red')
        console.log(f'+latitude: {lat}', style='green')
        console.log(f'+longitude: {lng}', style='green')
        self.latitude, self.longitude = lat, lng
        self.save()

    @staticmethod
    def _get_location_id_from_src(location_src: str) -> str:
        info = parse_loc_src(location_src)
        location = Location.from_id(info['id'])
        loc_dict = model_to_dict(location)
        for k, v in info.items():
            assert loc_dict[k] == v
        return info['id']

    def get_coordinate(self) -> tuple[float, float] | None:
        if self.latitude:
            return self.latitude, self.longitude
        if art_login := self.user.following:
            token = 'from=10DA093010&s=ba74941a'

        else:
            token = 'from=10CB193010&s=BF3838D9'

        url = ('https://api.weibo.cn/2/comments/build_comments?'
               f'launchid=10000365--x&c=iphone&{token}'
               f'&id={self.id}&is_show_bulletin=2')
        status = fetcher.get(url, art_login=art_login).json()[
            'status']
        if 'geo' not in status:
            console.log(
                f"seems have been deleted: {self.url} ", style='error')
        elif not (geo := status['geo']):
            console.log(f'no coord found: {self.url}', style='warning')
        else:
            lat, lng = geo['coordinates']
            lat, lng = round_loc(lat, lng)
            return lat, lng

    def medias(self, filepath: Path = None, extra=False) -> Iterator[dict]:
        if self.photos_extra:
            assert extra is True
        elif extra:
            return
        photos = (self.photos or []) + (self.photos_edited or [])
        prefix = f"{self.created_at:%y-%m-%d}_{self.username}_{self.id}"
        for sn, urls in enumerate(photos, start=1):
            if self.photos_extra and (urls not in self.photos_extra):
                continue
            for i, url in enumerate(urls.split('🎀')):
                aux = '_video' if i == 1 else ''
                if self.photos and sn > len(self.photos):
                    aux += '_edited'
                ext = parse_url_extension(url)
                yield {
                    "url": url,
                    "filename": f"{prefix}_{sn}{aux}{ext}",
                    "xmp_info": self.gen_meta(sn=sn, url=url),
                    "filepath": filepath,
                }
        if url := self.video_url:
            assert not self.photos_extra
            assert ";" not in url
            if (duration := self.video_duration) and duration > 600:
                console.log(f"video_duration is {duration})...skipping...")
            else:
                assert (ext := parse_url_extension(url)) == '.mp4'
                yield {
                    "url": url,
                    "filename": f"{prefix}{ext}",
                    "xmp_info": self.gen_meta(url=url),
                    "filepath": filepath,
                }

    def gen_meta(self, sn: str | int = '', url: str = "") -> dict:
        if photos := ((self.photos or [])+(self.photos_edited or [])):
            if (pic_num := len(photos)) == 1:
                assert not sn or int(sn) == 1
                sn = ""
            elif sn and pic_num > 9:
                sn = f"{int(sn):02d}"

        title = (self.text or "").strip()
        if self.region_name:
            title += f" 发布于{self.region_name}"
        xmp_info = {
            "ImageUniqueID": self.bid,
            "ImageSupplierID": self.user_id,
            "ImageSupplierName": "Weibo",
            "ImageCreatorName": self.username,
            "BlogTitle": title.strip(),
            "BlogURL": self.url,
            "Location": self.location,
            "DateCreated": (self.created_at +
                            pendulum.Duration(microseconds=int(sn or 0))),
            "SeriesNumber": sn,
            "URLUrl": url
        }

        xmp_info["DateCreated"] = xmp_info["DateCreated"].strftime(
            "%Y:%m:%d %H:%M:%S.%f").strip('0').strip('.')
        res = {"XMP:" + k: v for k, v in xmp_info.items() if v}
        if self.location_id:
            res['WeiboLocation'] = (self.latitude, self.longitude)
        return res

    def __str__(self):
        model = model_to_dict(self, recurse=False)
        res = {}
        for k, v in model.items():
            if 'count' in k or v is None:
                continue
            # if k in ['photos', 'pic_num', 'update_status']:
            #     continue
            res[k] = v
        return "\n".join(f'{k}: {v}' for k, v in res.items())


class Location(BaseModel):
    id = TextField(primary_key=True)
    short_name = TextField()
    name = TextField(index=True, null=True)
    address = TextField(null=True)
    latitude = DoubleField()
    longitude = DoubleField()
    country = TextField(null=True)
    url = TextField()
    url_m = TextField()
    version = TextField()

    @property
    def coordinate(self) -> tuple[float, float]:
        """
        return the (lat, lng) tuple
        """
        return self.latitude, self.longitude

    @classmethod
    def from_id(cls, location_id: str) -> Self | None:
        """
        return the Location instance from location_id
        or None if location has been deleted
        """
        if not cls.get_or_none(id=location_id):
            if info := (cls.get_location_info_v2(location_id)
                        or cls.get_location_info_v1p5(location_id)):
                cls.insert(info).execute()
            else:
                return
        return cls.get_by_id(location_id)

    @staticmethod
    def get_location_info_v2(location_id):
        api = f'http://place.weibo.com/wandermap/pois?poiid={location_id}'
        info = fetcher.get(api, art_login=True).json()
        if not info:
            return
        assert info.pop('poiid') == location_id
        lat, lng = round_loc(info.pop('lat'), info.pop('lng'))
        res = dict(
            id=location_id,
            short_name=info.pop('name'),
            address=info.pop('address') or None,
            latitude=lat,
            longitude=lng,
            country=info.pop('country') or None,
            url=f'https://weibo.com/p/100101{location_id}',
            url_m=('https://m.weibo.cn/p/index?'
                   f'containerid=2306570042{location_id}'),
            version='v2'
        )
        info.pop('pic')
        assert not info
        return res

    @staticmethod
    def get_location_info_v1p5(location_id: str) -> dict | None:
        url = f'https://weibo.com/p/100101{location_id}'
        url_m = ('https://m.weibo.cn/p/index?'
                 f'containerid=2306570042{location_id}')
        api = ('https://api.weibo.cn/2/cardlist?&from=10DA093010'
               f'&c=iphone&s=ba74941a&containerid=2306570042{location_id}')
        js = fetcher.get(api, art_login=True).json()
        cards = js['cards'][0]['card_group']
        pic = cards[0]['pic']
        if 'android_delete_poi.png' in pic:
            console.log(
                f'location has been deleted: {url} {url_m}', style='error')
            return

        if pic:
            pattern = r'longitude=(-?\d+\.\d+)&latitude=(-?\d+\.\d+)'
            lng, lat = map(float, re.search(pattern, pic).groups())
            lat, lng = round_loc(lat, lng)
            short_name = cards[1]['group'][0]['item_title']
            address = cards[3]['title'] if len(cards) >= 4 else None
            version = 'v1.5'
        else:
            scheme = cards[0]['scheme']
            pattern = r'latitude=(-?\d+\.\d+)&longitude=(-?\d+\.\d+)'
            lat, lng = map(float, re.search(pattern, scheme).groups())
            lat, lng = round_loc(lat, lng)
            short_name = js['cardlistInfo']['title_top']
            version = 'v1.0'
            address = cards[0]['title'].removeprefix('位于：')

        assert lng and lat
        return dict(
            id=location_id,
            latitude=lat,
            longitude=lng,
            short_name=short_name,
            address=address or None,
            url=url,
            url_m=url_m,
            version=version)


class Artist(BaseModel):
    username = CharField(index=True)
    user = ForeignKeyField(User, unique=True, backref='artist')
    age = IntegerField(null=True)
    photos_num = IntegerField(default=0)
    statuses_count = IntegerField()
    description = CharField(null=True)
    education = ArrayField(field_class=TextField, null=True)
    followed_by = ArrayField(field_class=TextField, null=True)
    follow_count = IntegerField()
    followers_count = IntegerField()
    homepage = CharField(null=True)
    added_at = DateTimeTZField(null=True, default=pendulum.now)

    _cache: dict[int, Self] = {}

    class Meta:
        table_name = "artist"

    @classmethod
    def from_id(cls, user_id: int, update: bool = False) -> Self:
        if not update and user_id in cls._cache:
            return cls._cache[user_id]
        user = User.from_id(user_id, update=update)
        user_dict = model_to_dict(user)
        user_dict['user_id'] = user_dict.pop('id')
        user_dict = {k: v for k, v in user_dict.items()
                     if k in cls._meta.columns}
        if cls.get_or_none(user_id=user_id):
            cls.update(user_dict).where(cls.user_id == user_id).execute()
        else:
            cls.insert(user_dict).execute()
        artist = cls.get(user_id=user_id)
        cls._cache[user_id] = artist
        return artist

    @property
    def xmp_info(self):
        xmp = {
            "Artist": self.username,
            "ImageCreatorID": self.homepage,
            "ImageSupplierID": self.user_id,
            "ImageSupplierName": "Weibo",
        }

        return {"XMP:" + k: v for k, v in xmp.items()}


class WeiboLiked(BaseModel):
    weibo_id = BigIntegerField()
    weibo_by = BigIntegerField()
    pic_num = IntegerField()
    user = ForeignKeyField(User, backref='weibos_liked')
    order_num = IntegerField()
    added_at = DateTimeTZField(default=pendulum.now)
    username = TextField()
    created_at = DateTimeTZField()

    class Meta:
        table_name = "liked"
        indexes = (
            (('user_id', 'order_num'), True),
            (('weibo_id', 'user_id'), True),
        )


class Friend(BaseModel):
    user = ForeignKeyField(User, backref='friends')
    username = TextField()
    friend_id = BigIntegerField()
    friend_name = TextField()
    gender = CharField()
    location = TextField()
    description = TextField()
    homepage = TextField()
    statuses_count = IntegerField()
    followers_count = IntegerField()
    follow_count = IntegerField()
    bi_followers_count = IntegerField()
    following = BooleanField()
    created_at = DateTimeTZField()
    avatar_hd = TextField()

    added_at = DateTimeTZField(default=pendulum.now)
    frequency = IntegerField(default=1)

    class Meta:
        table_name = "friend"
        indexes = (
            (('user_id', 'friend_id'), True),
        )

    @classmethod
    def update_frequency(cls):
        count = Counter(f.friend_id for f in cls)
        for friend in cls:
            if friend.frequency != count[friend.friend_id]:
                friend.frequency = count[friend.friend_id]
                friend.save()


tables = [User, UserConfig, Artist, Weibo, WeiboLiked, Location, Friend]
database.create_tables(tables)


class PG_BACK:
    def __init__(self, backpath: Path) -> None:
        self.backpath = backpath
        self.backpath.mkdir(exist_ok=True)
        self.backfile = self.backpath / 'pg_backup_latest.pkl'

    def backup(self):
        filename = f"pg_back_{pendulum.now().format('YYYYMMDD')}.pkl"
        backfile = self.backpath / filename
        databse_backup = {table._meta.table_name: list(
            table) for table in tables}
        with backfile.open('wb') as f:
            pickle.dump(databse_backup, f)
        if self.backfile.exists():
            self.backfile.unlink()
        self.backfile.hardlink_to(backfile)

    def restore(self):
        if not self.backfile.exists():
            console.log('No backup file found.', style='error')
            return
        with self.backfile.open('rb') as f:
            return pickle.load(f)
