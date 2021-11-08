from datetime import datetime
from typing import Optional, List, Dict

import pendulum
from sqlalchemy import DateTime, JSON, BigInteger, Column
from sqlmodel import SQLModel, Field, create_engine, Relationship

DATABASE = 'refresh'
database_url = f'postgresql://localhost/{DATABASE}'
engine = create_engine(database_url)


class Friend(SQLModel, table=True):
    user_id: int = Field(
        primary_key=True,
        foreign_key='user.id',
        sa_column=Column[BigInteger])

    friend_id: int = Field(
        primary_key=True,
        sa_column=Column[BigInteger])

    user: 'User' = Relationship(back_populates='friends')
    description: Optional[str]
    gender: str
    homepage: str
    avatar_hd: str

    def __str__(self):
        return f"""{self.dict()}"""


class UserConfig(SQLModel, table=True):
    id: int = Field(primary_key=True, foreign_key='user.id')
    user: 'User' = Relationship(back_populates='user_config')
    screen_name: str
    age: Optional[int]
    weibo_fetch: bool = False
    retweet_fetch: bool = False
    relation_fetch: bool = False
    following: bool
    education: Optional[List[str]]
    description: Optional[str]
    homepage: str
    weibo_update_at: datetime = Field(pendulum.from_timestamp(0))

    def __str__(self):
        text = ''
        for k, v in self.dict().items():
            from datetime import datetime
            if isinstance(v, datetime):
                v = v.strftime('%Y-%m-%d %H:%M:%S')
            text += f'{k}: {v}\n'
        return text




class Artist(SQLModel, table=True):
    id: int = Field(foreign_key='user.id', primary_key=True)
    user: 'User' = Relationship(back_populates='artist')
    user_name: str
    age: Optional[int]
    album: str
    photos_num: int = 0
    education: Optional[List[str]]
    description: Optional[str]
    homepage: Optional[str]
    statuses_count: int
    followers_count: int
    follow_count: int


class User(SQLModel, table=True):
    id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    weibos: List['Weibo'] = Relationship(back_populates='user')
    artist: Optional[Artist] = Relationship(back_populates='user')
    user_config: Optional[UserConfig] = Relationship(back_populates='user')
    friends: List['Friend'] = Relationship(back_populates='user')

    screen_name: str
    remark: Optional[str]
    following: bool
    birthday: str
    age: Optional[int]
    gender: str
    education: Optional[List[str]]
    location: str
    hometown: Optional[str]
    description: Optional[str]
    homepage: Optional[str]
    statuses_count: int
    followers_count: int
    follow_count: int
    follow_me: bool
    注册时间: str
    阳光信用: str
    性取向: Optional[str]
    verified: bool
    verified_type: int
    close_blue_v: bool
    mbtype: int
    urank: int
    mbrank: int
    avatar_hd: str
    like: bool
    like_me: bool
    info_updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True)))
    verified_type_ext: int
    verified_reason: str
    标签: str
    公司: str
    工作经历: str
    感情状况: str
    审核时间: str
    电话: str
    邮箱: str

    def __str__(self):
        text = ''
        keys = ['id', 'screen_name', 'gender', 'birthday', 'location', 'homepage',
                'description', 'statuses_count', 'followers_count', 'follow_count']
        for k in keys:
            if v := self.dict().get(k):
                text += f'{k}: {v}\n'
        return text


class Weibo(SQLModel, table=True):
    id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    bid: str

    user_id: int = Field(foreign_key="user.id")
    user: 'User' = Relationship(back_populates="weibos")

    screen_name: str
    text: str
    location: Optional[str]
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True)))
    at_users: List[str] = None
    topics: List[str] = None
    source: str

    original_id: Optional[int] = Field(foreign_key='weibo.id')
    original_bid: str = None
    original_uid: int = Field(None, sa_column=Column(BigInteger))
    original_text: str = None
    reposts_count: int
    comments_count: int
    attitudes_count: int
    url: str
    url_m: str
    photos: Dict[str, tuple[str, Optional[str]]] = Field(None, sa_column=Column(JSON))
    video_url: str = None
    video_duration: int = None

    def __str__(self):
        text = ''
        keys = [
            'screen_name', 'id', 'text', 'location',
            'created_at', 'at_users', 'url'
        ]
        for k in keys:
            if v := self.dict().get(k):
                text += f'{k}: {v}\n'
        return text


SQLModel.metadata.create_all(engine, tables=[p.__table__ for p in [Friend, UserConfig, Artist, User, Weibo]])
