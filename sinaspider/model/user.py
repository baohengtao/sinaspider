from collections import Counter
from typing import Self

import pendulum
from playhouse.postgres_ext import (
    ArrayField,
    BigIntegerField,
    BooleanField, CharField,
    DateTimeTZField,
    ForeignKeyField,
    IntegerField, TextField
)
from playhouse.shortcuts import model_to_dict

from sinaspider import console
from sinaspider.parser import UserParser

from .base import BaseModel


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
    async def from_id(cls, user_id: int, update=False) -> Self:
        if update or not cls.get_or_none(id=user_id):
            user_dict = await UserParser(user_id).parse()
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
            for s in (model_dict['education'] or []):
                if s not in edu:
                    edu.append(s)
            user_dict['education'] = edu

        if birth := user_dict.pop('birthday', model.birthday):
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

        for k, v in model_dict.items():
            if v is None or k in user_dict:
                continue
            if k in ['username', 'bilateral', 'description',
                     'IP', 'redirect', 'education']:
                continue
            if k in ['verified_reason', 'verified_type_ext',
                     'followed_by', '感情状况',]:
                user_dict[k] = None
                console.log(
                    f'-{k}: {model_dict[k]}', style='red bold on dark_red')
            else:
                console.log(f'{k}:{v} not in user_dict', style='warning')

        return cls.update(user_dict).where(cls.id == user_id).execute()

    def __str__(self):
        keys = ['avatar_hd', 'like', 'like_me', 'mbrank', 'mbtype', 'urank',
                'verified', 'verified_reason', 'verified_type',
                'verified_type_ext', 'svip', '公司', '工作经历',
                '性取向', '感情状况', '标签', '注册时间', '阳光信用']
        model = model_to_dict(self)
        return "\n".join(f"{k}: {v}" for k, v in model.items()
                         if v is not None and k not in keys)


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

    def __str__(self):
        return super().__repr__()

    @classmethod
    def from_id(cls, user_id: int, update: bool = False) -> Self:
        if not update and user_id in cls._cache:
            return cls._cache[user_id]
        user = User.get_by_id(user_id)
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

    def __str__(self):
        return super().__repr__()

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
