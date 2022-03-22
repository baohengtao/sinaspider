from datetime import datetime
from pathlib import Path
from typing import Optional, Generator, Iterator


import pendulum
from peewee import JOIN
from peewee import Model
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
    JSONField,
)

from sinaspider import console
from sinaspider.helper import download_files
from sinaspider.helper import normalize_wb_id, pause, normalize_user_id
from sinaspider.page import get_weibo_pages
from sinaspider.parser import get_weibo_by_id, get_user_by_id

database = PostgresqlExtDatabase("sinaspider", host="localhost")


class BaseModel(Model):
    class Meta:
        database = database


class User(BaseModel):
    id = BigIntegerField(primary_key=True, unique=True)
    username = TextField()
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
        table_name = "user"

    @classmethod
    def from_id(cls, user_id: int, update=False) -> Optional["User"]:
        user_id = normalize_user_id(user_id)
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

    def timeline(self, start_page=1,
                 since: int | str | datetime = "1970-01-01"):
        weibos = get_weibo_pages(f"107603{self.id}", start_page, since)
        yield from weibos

    def __str__(self):
        text = ""
        keys = [
            "id",
            "username",
            "gender",
            "birthday",
            "location",
            "homepage",
            "description",
            "statuses_count",
            "followers_count",
            "follow_count",
        ]
        for k in keys:
            if v := getattr(self, k, None):
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
    def from_id(cls, id):

        wb_id = normalize_wb_id(id)
        if not (weibo := Weibo.get_or_none(id=wb_id)):
            if not (weibo_dict := get_weibo_by_id(wb_id)):
                return
            weibo = Weibo(**weibo_dict)
            weibo.user = User.from_id(weibo.user_id)
            weibo.save(force_insert=True)
        return weibo

    def medias(self, filepath=None):
        photos = self.photos or {}
        for sn, urls in photos.items():
            for url in filter(bool, urls):
                *_, ext = url.split("/")[-1].split(".")
                if not _:
                    ext = "jpg"
                yield {
                    "url": url,
                    "filename": f"{self.user_id}_{self.id}_{sn}.{ext}",
                    "xmp_info": self.gen_meta(sn),
                    "filepath": filepath,
                }
        if url := self.video_url:
            assert ";" not in url
            if (duration := self.video_duration) and duration > 600:
                console.log(f"video_duration is {duration})...skipping...")
            else:
                yield {
                    "url": url,
                    "filename": f"{self.user_id}_{self.id}.mp4",
                    "xmp_info": self.gen_meta(),
                    "filepath": filepath,
                }

    def gen_meta(self, sn: str | int = 0) -> dict:
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
            "SeriesNumber": sn,
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
            if v := getattr(self, k, None):
                text += f"{k}: {v}\n"
        return text.strip()


# noinspection PyTypeChecker
class UserConfig(BaseModel):
    user = ForeignKeyField(User, unique=True)
    username = CharField()
    age = IntegerField(index=True, null=True)
    weibo_fetch = BooleanField(index=True, default=True)
    weibo_update_at = DateTimeTZField(
        index=True, default=pendulum.datetime(1970, 1, 1))
    following = BooleanField(null=True)
    description = CharField(index=True, null=True)
    education = CharField(index=True, null=True)
    homepage = CharField(index=True)

    class Meta:
        table_name = "userconfig"

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
        ]
        for k in fields:
            if (v := getattr(self, k, None)) is not None:
                if isinstance(v, datetime):
                    v = v.strftime("%Y-%m-%d %H:%M:%S")
                text += f"{k}: {v}\n"
        return text.strip()

    @classmethod
    def from_id(cls, user_id, save=True):
        user = User.from_id(user_id)
        if not (user_config := UserConfig.get_or_none(user=user)):
            user_config = UserConfig(user=user)
        fields = set(cls._meta.fields) - {"id"}
        for k in fields:
            if v := getattr(user, k, None):
                setattr(user_config, k, v)
        user_config.username = user.remark or user.username
        if save:
            user_config.save()
        return user_config

    @property
    def need_fetch(self):
        import math

        if not self.weibo_fetch:
            console.log(f"skip {self.username}...")
            return
        days = 100
        recent_num = (
            User.select(User)
            .join(Weibo, JOIN.LEFT_OUTER)
            .where(Weibo.created_at > pendulum.now().subtract(days=days))
            .where(User.id == self.user_id)
            .count()
        )
        update_interval = math.ceil(days * 1 / 2 * 1 / (recent_num + 1))
        update_interval = max(update_interval, 3)
        update_at = pendulum.instance(self.weibo_update_at)
        if update_at.diff().days < update_interval:
            console.log(f"skipping {self.username}"
                        f"for fetched at recent {update_interval} days")
            return False
        else:
            console.rule(
                f"开始获取 {self.username} "
                f"(update_at:{self.weibo_update_at:%y-%m-%d}; "
                f"update_interval:{update_interval})..."
            )
            return True

    def fetch_weibo(self, download_dir, start_page=1):

        User.from_id(self.user_id, update=True)
        now = pendulum.now()
        weibos = self.user.timeline(
            since=self.weibo_update_at, start_page=start_page)

        with console.status(
            f" [magenta]Fetching {self.username}...", spinner="christmas"
        ):
            console.log(self.user)
            console.log(f"Media Saving: {download_dir}")
            imgs = save_weibo(weibos, Path(download_dir) / self.username)
            download_files(imgs)
        console.log(f"{self.user.username}微博获取完毕")
        self.weibo_update_at = now
        self.save()
        pause(mode="user")

    @staticmethod
    def fetch_favorite(download_dir):
        weibos = get_weibo_pages(containerid="230259")
        with console.status("[magenta]Fetching favorite...",
                            spinner="christmas"):
            console.log(f"Media Saving: {download_dir}")
            imgs = save_weibo(weibos, Path(download_dir) / "favorite")
            download_files(imgs)
        console.log("收藏微博获取完毕")
        pause(mode="user")


class Artist(BaseModel):
    username = CharField(index=True)
    realname = CharField(null=True)
    user = ForeignKeyField(User, unique=True)
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

    class Meta:
        table_name = "artist"

    @classmethod
    def from_id(cls, user_id, update=False):
        user = User.from_id(user_id, update=update)
        if (artist := Artist.get_or_none(user_id=user.id)) is None:
            artist = Artist(user=user)
            artist.folder = "new"
        fields = set(cls._meta.fields) - {"id"}
        for k in fields:
            if v := getattr(user, k, None):
                setattr(artist, k, v)
        artist.username = user.remark or user.username.lstrip("-")
        if artist.username == artist.realname:
            artist.realname = None
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


database.create_tables([User, UserConfig, Artist, Weibo])


def save_weibo(
    weibos: Iterator[dict], download_dir: str | Path
) -> Generator[dict, None, None]:
    """
    Save weibo to database and return media info
    :param weibos: Iterator of weibo dict
    :param download_dir:
    :return: generator of medias to downloads
    """

    path = download_dir
    for weibo_dict in weibos:
        wb_id = weibo_dict["id"]
        wb_id = normalize_wb_id(wb_id)
        if not (weibo := Weibo.get_or_none(id=wb_id)):
            weibo = Weibo(**weibo_dict)
            weibo.user = User.from_id(weibo_dict["user_id"])
            weibo.username = weibo.user.username
            weibo.save(force_insert=True)

        medias = list(weibo.medias(path))
        console.log(weibo)
        if medias:
            console.log(f"Downloading {len(medias)} files to {path}..")
        print()
        yield from medias
