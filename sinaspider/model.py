import re
from datetime import datetime
from pathlib import Path
from typing import Iterator, Self

import pendulum
from bs4 import BeautifulSoup
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
    IntegerField, JSONField,
    PostgresqlExtDatabase,
    TextField
)
from playhouse.shortcuts import model_to_dict

from sinaspider import console
from sinaspider.helper import (
    download_files, fetcher,
    normalize_wb_id,
    parse_url_extension
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

        return "\n".join(f'{k}: {v}' for k, v in model.items() if v is not None)

    @classmethod
    def get_or_none(cls, *query, **filters) -> Self | None:
        return super().get_or_none(*query, **filters)

    @classmethod
    def get(cls, *query, **filters) -> Self:
        return super().get(*query, **filters)


class UserConfig(BaseModel):
    user: "User" = DeferredForeignKey("User", unique=True, backref='config')
    username = CharField()
    age = IntegerField(null=True)
    weibo_fetch = BooleanField(default=True)
    weibo_fetch_at = DateTimeTZField(null=True)
    liked_fetch = BooleanField(default=False)
    liked_fetch_at = DateTimeTZField(null=True)
    post_at = DateTimeTZField(null=True)
    following = BooleanField(null=True)
    description = CharField(index=True, null=True)
    education = ArrayField(field_class=TextField, null=True)
    homepage = CharField(index=True)
    visible = BooleanField(null=True)
    photos_num = IntegerField(null=True)
    followed_by = ArrayField(field_class=TextField, null=True)
    IP = TextField(null=True)

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
        if self.visible is True:
            return self.visible
        visible = self.page.get_visibility()
        if self.visible is None or visible is False:
            self.visible = visible
            self.save()
        else:
            console.log(
                f"conflict: {self.username}当前微博全部可见，请检查", style="error")
        return visible

    def fetch_weibo(self, download_dir: Path):
        if not self.weibo_fetch:
            return
        if self.weibo_fetch_at:
            since = pendulum.instance(self.weibo_fetch_at)
        else:
            since = pendulum.from_timestamp(0)
        console.rule(f"开始获取 {self.username} 的主页 (fetch_at:{since:%y-%m-%d})")
        console.log(self.user)
        console.log(f"Media Saving: {download_dir}")
        if not self.set_visibility():
            console.log(f"{self.username} 只显示半年内的微博", style="notice")

        now = pendulum.now()
        imgs = self._save_weibo(since, download_dir)
        download_files(imgs)
        console.log(f"{self.user.username}微博获取完毕\n")

        self.weibo_fetch_at = now
        for weibo_dict in self.page.homepage():
            if not weibo_dict.get('is_pinned'):
                self.post_at = weibo_dict['created_at']
                break
        self.save()

    def _save_weibo(
            self,
            since: pendulum.DateTime,
            download_dir: Path) -> Iterator[dict]:
        """
        Save weibo to database and return media info
        :return: generator of medias to downloads
        """

        if since > pendulum.now().subtract(years=1):
            user_root = 'Users'
        else:
            user_root = 'New'
        download_dir = Path(download_dir) / user_root / self.username

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
            weibo_id = Weibo.insert(weibo_dict).on_conflict(
                conflict_target=[Weibo.id],
                update=weibo_dict).execute()
            weibo = Weibo.get_by_id(weibo_id)

            medias = list(weibo.medias(download_dir))
            console.log(weibo)
            if medias:
                console.log(
                    f"Downloading {len(medias)} files to {download_dir}..")
            console.print()
            yield from medias

    def fetch_liked(self, download_dir: Path):
        if not self.liked_fetch:
            return
        console.rule(f"开始获取 {self.username} 的赞")
        console.log(f"Media Saving: {download_dir}")
        imgs = self._save_liked(download_dir / "Liked")
        download_files(imgs)
        if count := len(self._liked_list):
            (LikedWeibo
             .update(order_num=LikedWeibo.order_num + count)
             .where(LikedWeibo.user == self.user)
             .execute())
            LikedWeibo.insert_many(self._liked_list).execute()
            console.log(f"插入 {count} 条新赞")
            LikedWeibo.delete().where(LikedWeibo.order_num > 200).execute()
            self._liked_list.clear()

        console.log(f"{self.user.username}的赞获取完毕\n")
        self.liked_fetch_at = pendulum.now()
        self.save()

    def _save_liked(self, download_dir: Path) -> Iterator[dict]:
        download_dir /= self.username
        bulk = []
        early_stopping = False
        for weibo_dict in self.page.liked():
            weibo = Weibo(**weibo_dict)
            if UserConfig.get_or_none(user_id=weibo.user_id):
                continue
            if liked := LikedWeibo.get_or_none(
                    weibo_id=weibo.id, user_id=self.user_id):
                console.log(
                    f'{weibo.id}: early stopped by LikedWeibo'
                    f'with order_num {liked.order_num}',
                    style='warning')
                early_stopping = True
                break
            if len(weibo.photos) < weibo.pic_num:
                weibo_full = WeiboParser(weibo.id).parse()
                weibo = Weibo(**weibo_full)
            console.log(weibo)
            console.log(
                f"Downloading {len(weibo.photos)} files to {download_dir}..\n")
            prefix = f"{self.username}_{weibo.username}_{weibo.id}"
            for sn, (url, _) in weibo.photos.items():
                assert (ext := parse_url_extension(url))
                xmp_info = weibo.gen_meta(sn, url=url)
                description = weibo.url
                if xmp_info.get('XMP:BlogTitle'):
                    description += f" {xmp_info['XMP:BlogTitle']}"
                xmp_info.update({
                    'XMP:Title': f'{weibo.username}⭐️{self.username}',
                    'XMP:Description': description,
                    'XMP:Artist': weibo.username,
                    'XMP:ImageSupplierName': 'WeiboLiked',
                })

                yield {
                    "url": url,
                    "filename": f"{prefix}_{sn}{ext}",
                    "xmp_info": xmp_info,
                    "filepath": download_dir
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
                'order_num': i
            })


class User(BaseModel):
    id = BigIntegerField(primary_key=True, unique=True)
    username = TextField()
    screen_name = TextField()
    following = BooleanField()
    birthday = TextField(null=True)
    age = IntegerField(null=True)
    gender = TextField()
    education = ArrayField(field_class=TextField, null=True)
    location = TextField(null=True)
    followed_by = ArrayField(field_class=TextField, null=True)

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
    IP = TextField(null=True)
    svip = IntegerField(null=True)
    公司 = TextField(null=True)
    工作经历 = TextField(null=True)
    性取向 = TextField(null=True)
    感情状况 = TextField(null=True)
    标签 = TextField(null=True)
    注册时间 = TextField(null=True)
    阳光信用 = TextField(null=True)

    def __repr__(self):
        return super().__repr__()

    class Meta:
        table_name = "user"

    @classmethod
    def from_id(cls, user_id: int, update=False) -> Self:
        if not update:
            try:
                return cls.get_by_id(user_id)
            except cls.DoesNotExist:
                pass
        user_dict = UserParser(user_id).parse()
        if followed_by := user_dict.pop('followed_by', None):
            user_dict['followed_by'] = [
                u.username for u in cls.select().where(cls.id.in_(followed_by))]

        if cls.get_or_none(id=user_id):
            cls.update(user_dict).where(cls.id == user_id).execute()
        else:
            if 'username' not in user_dict:
                user_dict['username'] = user_dict['screen_name']
            cls.insert(user_dict).execute()
        return cls.get_by_id(user_id)

    def __str__(self):
        keys = [
            "id", "username", "following", "followed_by", "gender", "birthday", "location",
            "homepage", "description", "statuses_count", "followers_count", "follow_count", "IP"
        ]
        model = model_to_dict(self)
        return "\n".join(f"{k}: {v}" for k, v in model.items()
                         if k in keys and v is not None)


class Weibo(BaseModel):
    id = BigIntegerField(primary_key=True, unique=True)
    bid = TextField()
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
    photos = JSONField(null=True)
    video_duration = BigIntegerField(null=True)
    video_url = TextField(null=True)
    region_name = TextField(null=True)
    pic_num = IntegerField()
    update_status = TextField(null=True)
    latitude = DoubleField()
    longitude = DoubleField()

    class Meta:
        table_name = "weibo"

    @classmethod
    def from_id(cls, wb_id: int | str, update: bool = False) -> Self:
        wb_id = normalize_wb_id(wb_id)
        if not update:
            try:
                return Weibo.get_by_id(wb_id)
            except Weibo.DoesNotExist:
                pass
        weibo_dict = WeiboParser(wb_id).parse()
        Weibo.insert(weibo_dict).on_conflict(
            conflict_target=[Weibo.id],
            update=weibo_dict).execute()
        return cls.get_by_id(wb_id)

    def update_location(self):
        if not self.location_id or self.latitude:
            return
        location = Location.from_id(self.location_id)
        if not location.name:
            location.name = self.location
            location.save()
        else:
            assert location.name == self.location
        console.log(location)
        if coord := self.get_coordinate():
            if err := geodesic(coord, location.coordinate).meters:
                console.log(
                    f'the distance between coord and location is {err}m', style='notice')
        else:
            console.log(f'{self.url_m}: coord not found, use location coord',
                        style='warning')
        console.log()
        self.latitude, self.longitude = coord or location.coordinate
        self.save()

    def get_coordinate(self):
        url = ('https://api.weibo.cn/2/comments/build_comments?launchid=10000365--x'
               f'&from=10CB193010&c=iphone&s=BF3838D9&id={self.id}&is_show_bulletin=2')
        status = fetcher.get(url).json()['status']
        if 'geo' not in status:
            console.log(
                f"seems have been deleted: {self.url} ", style='error')
        elif geo := status['geo']:
            return geo['coordinates']

    def medias(self, filepath: Path = None) -> Iterator[dict]:
        photos = self.photos or {}
        prefix = f"{self.created_at:%y-%m-%d}_{self.username}_{self.id}"
        for sn, [photo_url, video_url] in photos.items():
            for i, url in enumerate([photo_url, video_url]):
                if url is None:
                    continue
                aux = '_video' if i == 1 else ''
                ext = parse_url_extension(url)
                yield {
                    "url": url,
                    "filename": f"{prefix}_{sn}{aux}{ext}",
                    "xmp_info": self.gen_meta(sn=sn, url=url),
                    "filepath": filepath,
                }
        if url := self.video_url:
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
        if sn and self.pic_num > 9:
            sn = f"{int(sn):02d}"
        title = (self.text or "").strip()
        if self.region_name:
            title += f" 发布于{self.region_name}"
        xmp_info = {
            "ImageUniqueID": self.bid,
            "ImageSupplierID": self.user_id,
            "ImageSupplierName": "Weibo",
            "ImageCreatorName": self.username,
            "BlogTitle": title,
            "BlogURL": self.url,
            "Location": self.location,
            "DateCreated": (self.created_at +
                            pendulum.Duration(microseconds=int(sn or 0))),
            "SeriesNumber": sn,
            "URLUrl": url
        }

        xmp_info["DateCreated"] = xmp_info["DateCreated"].strftime(
            "%Y:%m:%d %H:%M:%S.%f"
        )
        return {"XMP:" + k: v for k, v in xmp_info.items() if v}

    def __str__(self):
        model = model_to_dict(self, recurse=False)
        res = {}
        for k, v in model.items():
            if 'count' in k or v is None:
                continue
            if k in ['photos', 'pic_num', 'update_status']:
                continue
            res[k] = v
        return "\n".join(f'{k}: {v}' for k, v in res.items())


class Location(BaseModel):
    id = TextField(primary_key=True)
    short_name = TextField()
    name = TextField(index=True, null=True)
    latitude = DoubleField()
    longitude = DoubleField()
    url = TextField()
    url_m = TextField()

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
            if not (location_info := cls.get_location_info(location_id)):
                return
            cls.insert(location_info).execute()
        return cls.get_by_id(location_id)

    @staticmethod
    def get_location_info(location_id: str) -> dict | None:
        url = f'https://weibo.com/p/100101{location_id}'
        url_m = f'https://m.weibo.cn/p/index?containerid=2306570042{location_id}'
        api = f'https://m.weibo.cn/api/container/getIndex?containerid=2306570042{location_id}'
        js = fetcher.get(api).json()
        card = js['data']['cards'][0]['card_group']
        pic = card[0]['pic']
        if 'android_delete_poi.png' in pic:
            console.log(
                f'location has been deleted: {url} {url_m}', style='error')
            return
        pattern = 'longitude=(-?\d+\.\d+)&latitude=(-?\d+\.\d+)'
        lng, lat = re.search(pattern, pic).groups()
        short_name = card[1]['group'][0]['item_title']
        assert lng and lat
        return dict(
            id=location_id,
            latitude=float(lat),
            longitude=float(lng),
            url=url,
            url_m=url_m,
            short_name=short_name)


class Artist(BaseModel):
    username = CharField(index=True)
    user = ForeignKeyField(User, unique=True, backref='artist')
    age = IntegerField(null=True)
    folder = CharField(null=True, default="new")
    photos_num = IntegerField(default=0)
    favor_num = IntegerField(default=0)
    recent_num = IntegerField(default=0)
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


class LikedWeibo(BaseModel):
    weibo_id = BigIntegerField()
    weibo_by = BigIntegerField()
    pic_num = IntegerField()
    user = ForeignKeyField(User, backref='liked_weibos')
    order_num = IntegerField()
    added_at = DateTimeTZField(default=pendulum.now)

    class Meta:
        table_name = "liked"
        indexes = (
            (('user_id', 'order_num'), True),
            (('weibo_id', 'user_id'), True),
        )


database.create_tables([User, UserConfig, Artist, Weibo, LikedWeibo, Location])
