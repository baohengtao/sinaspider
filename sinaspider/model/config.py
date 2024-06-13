from pathlib import Path
from typing import Iterator, Self

import pendulum
from playhouse.postgres_ext import (
    ArrayField, BooleanField,
    CharField,
    DateTimeTZField,
    ForeignKeyField,
    IntegerField, TextField
)
from playhouse.shortcuts import model_to_dict

from sinaspider import console
from sinaspider.helper import download_files, fetcher, parse_url_extension
from sinaspider.page import Page

from .base import BaseModel
from .user import Friend, User
from .weibo import Weibo, WeiboCache, WeiboLiked


class UserConfig(BaseModel):
    user: "User" = ForeignKeyField(User, unique=True, backref='config')
    username = CharField()
    nickname = CharField(null=True)
    age = IntegerField(null=True)
    weibo_fetch = BooleanField(null=True)
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
    weibo_cache_at = DateTimeTZField(default=None, null=True)

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
        if not (self.weibo_fetch_at or self.weibo_cache_at):
            self.visible = None
        if self.visible is True:
            return True
        visible = self.page.get_visibility()
        if self.visible is None or visible is False:
            self.visible = visible
            self.save()
        elif self.weibo_cache_at:
            console.log(f'{self.username} 当前显示全部微博', style='warning')
            console.log('reset weibo_cache_at to None', style='warning')
            self.weibo_cache_at = None
            self.visible = visible
            self.save()
        else:
            raise ValueError(
                f"conflict: {self.username}当前微博全部可见，请检查")
        if not visible:
            console.log(f"{self.username} 只显示半年内的微博", style="notice")
        return visible

    def get_homepage(self,
                     since: pendulum.DateTime,
                     skip_exist: bool = False,
                     ) -> 'Weibo':
        for mblog in self.page.homepage():
            is_pinned = mblog.pop('is_pinned')
            created_at = pendulum.from_format(
                mblog['created_at'], 'ddd MMM DD HH:mm:ss ZZ YYYY')
            if created_at < since:
                if is_pinned:
                    console.log("略过置顶微博...")
                    continue
                else:
                    console.log(
                        f"时间 {created_at:%y-%m-%d} 在 "
                        f"{since:%y-%m-%d}之前, 获取完毕")
                    break
            weibo = Weibo.get_or_none(id=mblog['id'])
            insert_at = weibo and (weibo.updated_at or weibo.added_at)
            if insert_at and skip_exist:
                continue
            if not insert_at or insert_at < pendulum.now().subtract(minutes=50):
                weibo_dict = WeiboCache.upsert(mblog).parse()
                weibo_dict['username'] = self.username
                weibo = Weibo.upsert(weibo_dict)
            yield weibo

    def caching_weibo_for_new(self):
        if self.weibo_fetch is not None:
            assert self.weibo_cache_at is None
            assert self.weibo_fetch or self.weibo_fetch_at
            return
        else:
            assert self.weibo_fetch_at is None

        since = self.weibo_cache_at or pendulum.from_timestamp(0)
        console.rule(
            f"caching {self.username}'s homepage (cached at {since:%y-%m-%d})")
        console.log(self.user)

        now, i = pendulum.now(), 0
        for i, weibo in enumerate(
                self.get_homepage(since, skip_exist=True), start=1):
            if weibo.photos_extra:
                weibo.photos_extra = None
                weibo.save()
            console.log(weibo)
            weibo.highlight_social()
            console.log()
        console.log(f'{i} weibos cached for {self.username}')
        media_count = [len(list(weibo.medias())) for weibo in self.user.weibos]
        console.log(
            f'{self.username} have {len(media_count)} weibos '
            f'with {sum(media_count)} media files', style='notice')
        self.weibo_cache_at = now
        self.weibo_next_fetch = self.get_weibo_next_fetch()
        if weibos := self.user.weibos.order_by(Weibo.created_at.desc()):
            self.post_at = weibos[0].created_at
        self.save()

    def fetch_weibo(self, download_dir: Path):
        if self.weibo_fetch is False:
            return
        fetcher.toggle_art(self.following)
        self.set_visibility()
        self.fetch_friends()
        if self.weibo_fetch is None:
            self.caching_weibo_for_new()
            return
        if self.weibo_fetch_at:
            msg = f"weibo_fetch:{self.weibo_fetch_at:%y-%m-%d}"
        else:
            msg = f'weibo_fetch:{self.weibo_fetch}'
        if self.liked_fetch_at:
            msg += f" liked_fetch: {self.liked_fetch_at:%y-%m-%d}"
        else:
            msg += f" liked_fetch: {self.liked_fetch}"
        console.rule(f"开始获取 {self.username} 的主页 ({msg})")
        console.log(self.user)
        console.log(f"Media Saving: {download_dir}")

        now = pendulum.now()
        imgs = self._save_weibo(download_dir)
        download_files(imgs)
        console.log(f"{self.username}微博获取完毕\n")
        self.weibo_fetch_at = now
        self.weibo_next_fetch = self.get_weibo_next_fetch()
        self.weibo_cache_at = None
        if weibos := self.user.weibos.order_by(Weibo.created_at.desc()):
            self.post_at = weibos[0].created_at
        self.save()

    def _save_weibo(
            self,
            download_dir: Path) -> Iterator[dict]:
        """
        Save weibo to database and return media info
        :return: generator of medias to downloads
        """

        if self.weibo_fetch_at is None:
            user_root = 'User'
        elif not self.photos_num:
            console.log(
                f'seems {self.username} not processed, using User folder',
                style='green on dark_green')
            user_root = 'User'
        else:
            user_root = 'Timeline'
        download_dir = download_dir / user_root / self.username

        since = self.weibo_fetch_at or pendulum.from_timestamp(0)
        console.log(f'fetch weibo from {since:%Y-%m-%d}\n')
        weibo_ids = []
        for weibo in self.get_homepage(since):

            weibo_ids.append(weibo.id)

            console.log(weibo)
            weibo.highlight_social()

            if medias := list(weibo.medias(download_dir)):
                console.log(
                    f"Downloading {len(medias)} files to {download_dir}..")
                yield from medias
            console.log()
        if self.weibo_fetch_at:
            return
        if weibos := self.user.weibos.where(Weibo.id.not_in(weibo_ids)):
            console.log(
                f'{len(weibos)} weibos not visible now but cached, saving...',
                style='warning')
            for weibo in weibos.order_by(Weibo.id.desc()):
                if weibo.username != self.username:
                    weibo.username = self.username
                    weibo.save()
                console.log(weibo)
                weibo.highlight_social()
                if medias := list(weibo.medias(download_dir)):
                    console.log(
                        f"Downloading {len(medias)} files to {download_dir}..")
                    yield from medias
                console.log()

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
        if fids and (added := (fids_updated-fids)):
            console.log('following user be added')
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
        download_dir /= 'Liked'
        dir_saved = download_dir / '_saved'
        dir_new = download_dir / f'_Liked_New/{self.username}'
        if not self.liked_fetch_at or dir_new.exists():
            download_dir = dir_new
        else:
            folders = [f for f in download_dir.iterdir() if f.is_dir()
                       and f.name.split('_')[0] == self.username]
            if folders:
                assert len(folders) == 1
                download_dir = folders[0]
            else:
                download_dir /= f'{self.username}_{self.liked_fetch_at:%y-%m-%d}'
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
            filepath = dir_saved if config else download_dir

            if liked := WeiboLiked.get_or_none(
                    weibo_id=wid, user_id=self.user_id):
                console.log(
                    f'{wid}: early stopped by WeiboLiked'
                    f'with order_num {liked.order_num}',
                    style='warning')
                early_stopping = True
                break
            try:
                weibo_dict = WeiboCache.upsert(mblog).parse()
            except KeyError as e:
                console.log(
                    f'{e}: cannot parse https://weibo.com/{uid}/{wid}, '
                    'skipping...', style='error')
                continue

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
                    f'https://weibo.com/u/{weibo.user_id}'
                ])
                xmp_info.update({
                    'XMP:Title': f'{weibo.username}⭐️{self.username}',
                    'XMP:Description': description,
                    'XMP:Artist': weibo.username,
                    'XMP:ImageSupplierName': 'WeiboLiked',
                    'XMP:MakerNote': mblog
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
        days = max(min(duration.in_days(), 180), 15)
        return liked_fetch_at.add(days=days)

    def get_weibo_next_fetch(self) -> pendulum.DateTime:
        if not (update_at := self.weibo_fetch_at or self.weibo_cache_at):
            return
        if self.blocked:
            return
        update_at = pendulum.instance(update_at)
        days = 30
        posts = len(self.user.weibos
                    .where(Weibo.created_at > update_at.subtract(days=days))
                    .where(Weibo.has_media))
        interval = days / (posts + 1)

        if not self.is_friend and not self.following:
            interval = min(interval, 2)
        return update_at.add(days=interval)

    @classmethod
    def update_table(cls):
        from photosinfo.model import Girl

        for config in cls:
            config: cls
            if config.weibo_fetch is None:
                assert config.weibo_fetch_at is None
            elif config.weibo_fetch is True:
                assert not (config.weibo_cache_at and config.weibo_fetch_at)
            else:
                assert config.weibo_fetch_at and not config.weibo_cache_at

            config.username = config.user.username
            if girl := Girl.get_or_none(username=config.username):
                config.photos_num = girl.sina_num
                config.folder = girl.folder
            else:
                config.photos_num = 0
            config.weibo_next_fetch = config.get_weibo_next_fetch()
            config.liked_next_fetch = config.get_liked_next_fetch()
            config.save()
