from datetime import datetime
from pathlib import Path
from typing import Iterator, Self

import pendulum
from peewee import JOIN
from peewee import Model
from playhouse.shortcuts import model_to_dict
from playhouse.postgres_ext import (
    PostgresqlExtDatabase,
    IntegerField,
    BooleanField,
    TextField,
    BigIntegerField,
    DateTimeTZField,
    ArrayField,
    CharField,
    ForeignKeyField,
    DeferredForeignKey,
    JSONField,
)

from sinaspider import console
from sinaspider.helper import download_files, parse_url_extension
from sinaspider.helper import normalize_wb_id, pause, normalize_user_id
from sinaspider.page import Page
from sinaspider.parser import WeiboParser, UserParser

database = PostgresqlExtDatabase("sinaspider", host="localhost")


class BaseModel(Model):
    class Meta:
        database = database

    def __repr__(self):
        model = model_to_dict(self, recurse=False)
        return "\n".join(f'{k}: {v}' for k, v in model.items())


class UserConfig(BaseModel):
    user: "User" = DeferredForeignKey("User", unique=True, backref='config')
    username = CharField()
    age = IntegerField(null=True)
    weibo_fetch = BooleanField(default=True)
    weibo_update_at = DateTimeTZField(default=pendulum.datetime(1970, 1, 1))
    liked_fetch = BooleanField(default=False)
    liked_update_at = DateTimeTZField(null=True)
    following = BooleanField(null=True)
    description = CharField(index=True, null=True)
    education = CharField(index=True, null=True)
    homepage = CharField(index=True)
    visible = BooleanField(null=True)
    photos_num = IntegerField(null=True)
    IP = TextField(null=True)

    class Meta:
        table_name = "userconfig"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.page = Page(self.user_id)

    def __repr__(self):
        return super().__repr__()

    def __str__(self):
        text = ""
        fields = [
            "username",
            "age",
            "education",
            "following",
            "description",
            "homepage",
            "weibo_fetch",
            "weibo_update_at",
            "IP"
        ]
        for k in fields:
            if (v := getattr(self, k, None)) is not None:
                if isinstance(v, datetime):
                    v = v.strftime("%Y-%m-%d %H:%M:%S")
                text += f"{k}: {v}\n"
        return text.strip()

    @classmethod
    def from_id(cls, user_id) -> Self:
        user = User.from_id(user_id, update=True)
        if not (user_config := UserConfig.get_or_none(user=user)):
            user_config = UserConfig(user=user)
        fields = set(cls._meta.fields) - {"id"}
        for k in fields:
            try:
                v = getattr(user, k)
            except AttributeError:
                continue
            else:
                setattr(user_config, k, v)

        user_config.save()
        return user_config

    def set_visibility(self) -> bool:
        if self.visible is True:
            return self.visible
        last_page = self.user.statuses_count // 20
        while True:
            weibos = self.page.homepage(start_page=last_page)
            try:
                weibo = next(weibos)
            except StopIteration:
                visibility = False
                break
            else:
                if weibo['created_at'] < pendulum.now().subtract(months=6):
                    visibility = True
                    break
                else:
                    last_page += 1

        if self.visible is None:
            self.visible = visibility
            self.save()
        else:
            assert visibility is False
        return self.visible

    @property
    def need_fetch(self) -> bool:
        import math

        if not self.weibo_fetch:
            console.log(f"skip {self.username}...")
            return
        days = 90
        recent_num = (
            User.select(User)
            .join(Weibo, JOIN.LEFT_OUTER)
            .where(Weibo.created_at > pendulum.now().subtract(days=days))
            .where(Weibo.photos.is_null(False))
            .where(User.id == self.user_id)
            .count()
        )
        update_interval = math.ceil(days / (recent_num + 2))
        update_interval = max(update_interval, 7)
        update_at = pendulum.instance(self.weibo_update_at)
        if update_at.diff().days < update_interval:
            console.log(f"skipping {self.username}"
                        f"for fetched at recent {update_interval} days")
            return False
        else:
            return True

    def fetch_weibo(self, download_dir: Path):
        if not self.weibo_fetch:
            return
        since = pendulum.instance(self.weibo_update_at)
        console.rule(f"开始获取 {self.username} 的主页(update_at:{since:%y-%m-%d})")
        console.log(self.user)
        console.log(f"Media Saving: {download_dir}")
        self.set_visibility()
        now = pendulum.now()
        imgs = self._save_weibo(since, download_dir)
        download_files(imgs)
        console.log(f"{self.user.username}微博获取完毕\n")

        self.weibo_update_at = now
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

        for weibo_dict in self.page.homepage(since=since):
            assert weibo_dict['user_id'] == self.user_id
            current_fields = set(Weibo._meta.fields) | {"user_id", "pic_num"}
            if extra_fields := set(weibo_dict) - current_fields:
                console.log(
                    f"find extra fields: {extra_fields}", style='error')
            wb_id = weibo_dict["id"]
            if weibo := Weibo.get_or_none(id=wb_id):
                force_insert = False
            else:
                weibo = Weibo()
                force_insert = True
            for k, v in weibo_dict.items():
                setattr(weibo, k, v)
            weibo.username = self.username
            weibo.save(force_insert=force_insert)

            medias = list(weibo.medias(download_dir))
            console.log(weibo)
            if medias:
                console.log(
                    f"Downloading {len(medias)} files to {download_dir}..")
            console.print()
            yield from medias

    def fetch_liked(self, download_dir):
        if not self.liked_fetch:
            return
        console.rule(f"开始获取 {self.username} 的赞")
        now = pendulum.now()
        console.log(f"Media Saving: {download_dir}")
        imgs = self._save_liked(download_dir=Path(download_dir) / "Liked")
        download_files(imgs)
        if count := len(self._liked_insert):
            (LikedWeibo
             .update(order_num=LikedWeibo.order_num + count)
             .where(LikedWeibo.user == self.user)
             .execute())
            LikedWeibo.insert_many(self._liked_insert).execute()
            LikedWeibo.delete().where(LikedWeibo.order_num > 200).execute()

        self._liked_insert = None
        console.log(f"{self.user.username}的赞获取完毕\n")
        self.liked_update_at = now
        self.save()
        pause(mode="user")

    def _save_liked(self, download_dir: Path) -> Iterator[dict]:
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
                weibo_full = WeiboParser.from_id(weibo.id).parse()
                weibo = Weibo(**weibo_full)
            console.log(weibo)
            console.log(
                f"Downloading {len(weibo.photos)} files to {download_dir}..\n")
            prefix = f"{self.username}_{weibo.username}_{weibo.id}"
            for sn, (url, _) in weibo.photos.items():
                assert (ext := parse_url_extension(url))

                xmp_info = weibo.gen_meta(sn, url=url)
                xmp_info.update({
                    'XMP:Title': f'{weibo.username}⭐️{self.username}',
                    'XMP:Description': weibo.url,
                    'XMP:Artist': weibo.username,
                    'XMP:ImageSupplierName': 'WeiboLiked',
                })

                yield {
                    "url": url,
                    "filename": f"{prefix}_{sn}{ext}",
                    "xmp_info": xmp_info,
                    "filepath": download_dir / self.username
                }
            bulk.append(weibo)
        if early_stopping and not self.liked_update_at:
            console.log(
                'early stopping but liked_update_at is not set', style='error')
        elif not early_stopping and self.liked_update_at:
            console.log(
                'liked_update_at is set but not early stopping', style='error')

        bulk_insert = []
        for i, weibo in enumerate(bulk, start=1):
            bulk_insert.append({
                'weibo_id': weibo.id,
                'weibo_by': weibo.user_id,
                'pic_num': weibo.pic_num,
                'user_id': self.user_id,
                'order_num': i
            })
        assert getattr(self, '_liked_insert', None) is None
        self._liked_insert: list = bulk_insert


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
    IP = TextField(null=True)
    svip = IntegerField(null=True)

    def __repr__(self):
        return super().__repr__()

    class Meta:
        table_name = "user"

    @classmethod
    def from_id(cls, user_id: int, update=False) -> Self:
        user_id = normalize_user_id(user_id)
        if (user := User.get_or_none(id=user_id)) is None:
            force_insert = True
            update = True
            user = User()
        else:
            force_insert = False
        if not update:
            return user
        user_dict = UserParser(user_id).user
        for k, v in user_dict.items():
            setattr(user, k, v)
        user.username = user.username or user.screen_name
        if extra_fields := set(user_dict) - set(cls._meta.fields):
            extra_info = {k: user_dict[k] for k in extra_fields}
            raise ValueError(f'some fields not saved to model: {extra_info}')
        user.save(force_insert=force_insert)

        return cls.get_by_id(user_id)

    def __str__(self):
        text = ""
        keys = [
            "id",
            "username",
            "following",
            "gender",
            "birthday",
            "location",
            "homepage",
            "description",
            "statuses_count",
            "followers_count",
            "follow_count",
            "IP"
        ]
        for k in keys:
            if (v := getattr(self, k, None)) is not None:
                text += f"{k}: {v}\n"
        return text.strip()


class Weibo(BaseModel):
    id = BigIntegerField(primary_key=True, unique=True)
    bid = TextField(null=True)
    user = ForeignKeyField(User, backref="weibos")
    username = TextField(null=True)
    created_at = DateTimeTZField(null=True)
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
        table_name = "weibo"

    @classmethod
    def from_id(cls, wb_id, update=False) -> Self:
        wb_id = normalize_wb_id(wb_id)
        if not (weibo := cls.get_or_none(id=wb_id)):
            force_insert = True
            update = True,
            weibo = cls()
        else:
            force_insert = False
        if not update:
            return weibo

        weibo_dict = WeiboParser.from_id(wb_id).parse()
        for k, v in weibo_dict.items():
            setattr(weibo, k, v)
        weibo.save(force_insert=force_insert)
        return cls.get_by_id(wb_id)

    def medias(self, filepath=None):
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

    def gen_meta(self, sn: str | int = 0, url: str = "") -> dict:
        sn = int(sn) if sn else 0
        xmp_info = {
            "ImageUniqueID": self.bid,
            "ImageSupplierID": self.user_id,
            "ImageSupplierName": "Weibo",
            "ImageCreatorName": self.username,
            "BlogTitle": self.text,
            "BlogURL": self.url,
            "Location": self.location,
            "DateCreated": (self.created_at +
                            pendulum.Duration(microseconds=int(sn))),
            "SeriesNumber": sn if sn else '',
            "URLUrl": url
        }

        xmp_info["DateCreated"] = xmp_info["DateCreated"].strftime(
            "%Y:%m:%d %H:%M:%S.%f"
        )
        return {"XMP:" + k: v for k, v in xmp_info.items() if v}

    def __str__(self):
        text = ""
        keys = [
            "user_id",
            "username",
            "id",
            "text",
            "location",
            "created_at",
            "at_users",
            "url",
        ]
        for k in keys:
            if (v := getattr(self, k, None)) is not None:
                text += f"{k}: {v}\n"
        return text.strip()

    def __repr__(self):
        return super().__repr__()


class Artist(BaseModel):
    username = CharField(index=True)
    realname = CharField(null=True)
    user = ForeignKeyField(User, unique=True, backref='artist')
    age = IntegerField(index=True, null=True)
    folder = CharField(index=True, null=True)
    photos_num = IntegerField(default=0)
    favor_num = IntegerField(default=0)
    recent_num = IntegerField(default=0)
    statuses_count = IntegerField(index=True)
    description = CharField(index=True, null=True)
    education = CharField(index=True, null=True)
    follow_count = IntegerField(index=True)
    followers_count = IntegerField(index=True)
    homepage = CharField(index=True, null=True)
    added_at = DateTimeTZField(null=True)

    class Meta:
        table_name = "artist"

    def __repr__(self):
        return super().__repr__()

    @classmethod
    def from_id(cls, user_id, update=False):
        user = User.from_id(user_id, update=update)
        if (artist := Artist.get_or_none(user_id=user.id)) is None:
            artist = Artist(user=user)
            artist.folder = "new"
            artist.added_at = pendulum.now()
        fields = set(cls._meta.fields) - {"id"}
        fields &= set(User._meta.fields)
        for k in fields:
            if v := getattr(user, k):
                setattr(artist, k, v)
        artist.save()
        return artist

    @property
    def xmp_info(self):
        xmp = {
            "Artist": self.realname or self.username,
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

    def __repr__(self):
        return super().__repr__()

    def __str__(self) -> str:
        return self.__repr__()


database.create_tables([User, UserConfig, Artist, Weibo, LikedWeibo])
