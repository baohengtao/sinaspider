from datetime import datetime
from pathlib import Path
from typing import Union, Optional

import pendulum

from sinaspider import logger
from sinaspider.model import User, Weibo, Artist, UserConfig, Friend
from sinaspider.util.helper import convert_wb_bid_to_id, get_url, write_xmp
from sinaspider.util.helper import pause
from sinaspider.util.page import get_weibo_pages, get_follow_pages
from sinaspider.util.parser import get_user_by_id


class UserConfigMethod:

    def __init__(self, user_id, session):
        self.id = user_id
        self.user = UserMethod.from_id(user_id, session)
        self.user_method = UserMethod(self.user)
        self.session = session
        if not (user_config := self.session.get(UserConfig, user_id)):
            user_config = UserConfig(**self.user.dict())
        else:
            for k, v in self.user.dict().items():
                if k in UserConfig.__fields__:
                    setattr(user_config, k, v)
        user_config.screen_name = self.user.remark or self.user.screen_name
        self.session.add(user_config)
        self.session.commit()
        self.user_config = self.session.get(UserConfig, user_id)

    def fetch_friends(self):
        for friend in self.user_method.friends():
            if not self.session.get(Friend, {'friend_id': friend.friend_id, 'user_id': friend.user_id}):
                self.session.add(friend)
                self.session.commit()

    def fetch_weibo(self, download_dir=None, update_interval=5, update=True):
        if not self.user_config.weibo_fetch:
            print(f'skip {self.user.screen_name}...')
            return
        weibo_since, now = self.user_config.weibo_update_at, pendulum.now()
        if pendulum.instance(weibo_since).diff().days < update_interval:
            print(f'skipping...for fetched at recent {update_interval} days')
            return
        UserMethod.from_id(self.id, self.session, update=True)
        print(self.user)

        weibos = self.user_method.weibos(since=weibo_since)
        logger.info(
            f'正在获取用户 {self.user.screen_name} 自 {weibo_since:%y-%m-%d} 起的所有微博')
        logger.info(f"Fetching Retweet: {self.user_config.retweet_fetch}")
        logger.info(f"Media Saving: {download_dir or False}")
        # logger.info(f"Update Config: {update}")

        for nt_weibo in weibos:
            original, retweet = WeiboMethod.add_to_table(
                *nt_weibo, session=self.session)
            if not retweet:
                original_dir = Path(download_dir) / self.user.screen_name
                WeiboMethod(original).save_media(original_dir)
            elif self.user_config.retweet_fetch:
                retweet_dir = Path(download_dir) / \
                    'retweet' / self.user.screen_name
                WeiboMethod(original).save_media(retweet_dir)
            else:
                continue
            print(retweet or original)
        logger.success(f'{self.user.screen_name}微博获取完毕')
        if update:
            self.user_config.weibo_update_at = now
            self.session.add(self.user_config)
            self.session.commit()

        pause(mode='user')

    def display_friends(self):
        from IPython.display import Image, display
        import requests
        for f in self.user.friends:
            if f.gender == 'male':
                continue
            display(Image(requests.get(f.avatar_hd).content))
            print(f)


class WeiboMethod:

    def __init__(self, weibo: Weibo):
        self.id = weibo.id
        self.user_id = weibo.user_id
        self.weibo = weibo

    @classmethod
    def from_id(cls, id, session):
        from sinaspider.util.parser import get_weibo_by_id
        try:
            id = int(id)
        except ValueError:
            id = convert_wb_bid_to_id(id)

        if weibo := session.get(Weibo, id):
            return weibo
        elif nt_weibo := get_weibo_by_id(id):
            weibo, original = nt_weibo
            cls.add_to_table(weibo, original, session=session)
            return Weibo(**weibo)

    @classmethod
    def add_to_table(cls, *weibos: dict, session):
        res = []
        for w in weibos:
            if w is None:
                res.append(w)
            else:
                if d := set(w) - set(Weibo.__fields__):
                    logger.warning(d)

                wa = session.get(Weibo, w['id']) or Weibo()
                for k, v in w.items():
                    if k in Weibo.__fields__:
                        setattr(wa, k, v)
                logger.info(weibos)
                assert wa.user_id
                UserMethod.from_id(wa.user_id, session)
                session.add(wa)
                session.commit()
                session.refresh(wa)
                res.append(wa)
        return res

    def medias(self):
        photos = self.weibo.photos or {}
        for sn, urls in photos.items():
            for url in filter(bool, urls):
                ext = url.split('.')[-1]
                filename = f'{self.user_id}_{self.id}_{sn}.{ext}'
                yield {
                    'url': url,
                    'filename': filename,
                    'xmp_info': self.gen_meta(sn)
                }
        if url := self.weibo.video_url:
            assert ';' not in url
            if (duration := self.weibo.video_duration) and duration > 600:
                logger.warning(f'video_duration is {duration})...skipping...')
            else:
                yield {
                    'url': url,
                    'filename': f'{self.user_id}_{self.id}.mp4',
                    'xmp_info': self.gen_meta()
                }

    def save_media(self, download_dir):
        path = Path(download_dir)
        path.mkdir(parents=True, exist_ok=True)
        medias = list(self.medias())
        for file in medias:
            filepath = path / file['filename']
            if filepath.exists():
                logger.warning(
                    f'{filepath} already exists..skip {file["url"]}')
                continue
            downloaded = get_url(file['url']).content
            filepath.write_bytes(downloaded)
            write_xmp(file['xmp_info'], filepath)
        logger.info(
            f"{self.id}: Downloading {len(medias)} files to {download_dir}...")

    def gen_meta(self, sn: Union[str, int] = 0) -> dict:
        weibo = self.weibo
        sn = int(sn) if sn else 0
        xmp_info = {
            'ImageUniqueID': weibo.bid,
            'ImageSupplierID': weibo.user_id,
            'ImageSupplierName': 'Weibo',
            'ImageCreatorName': weibo.screen_name,
            'BlogTitle': weibo.text,
            'BlogURL': weibo.url,
            'Location': weibo.location,
            'DateCreated': weibo.created_at + pendulum.Duration(microseconds=int(sn)),
            'SeriesNumber': sn
        }

        xmp_info['DateCreated'] = xmp_info['DateCreated'].strftime(
            '%Y:%m:%d %H:%M:%S.%f')
        return {'XMP:' + k: v for k, v in xmp_info.items() if v}


class UserMethod:

    def __init__(self, user: User):
        self.user = user
        self.id = user.id
        self.follow_page = '231051_-_followers_-_%s' % self.id
        self.fan_page = '231051_-_fans_-_%s' % self.id
        self.weibo_page = '107603%s' % self.id

    def weibos(self, start_page=1, end_page=None, since: Union[int, str, datetime] = '1970-01-01'):
        weibos = get_weibo_pages(self.weibo_page, start_page, end_page, since)
        yield from weibos

    @staticmethod
    def collections():
        weibos = get_weibo_pages(containerid='230259')
        yield from weibos

    def follow(self):
        yield from get_follow_pages(self.follow_page)

    def friends(self):
        logger.info('正在获取关注页面')
        follow = [User(**u) for u in get_follow_pages(self.follow_page)]
        logger.info(f"共获取 {len(follow)}/{self.user.follow_count} 个关注")
        fan = {u['id'] for u in get_follow_pages(self.fan_page)}
        logger.info(f"共获取 {len(fan)}/{self.user.followers_count} 个粉丝")
        for u in follow:
            if u.id in fan:
                yield Friend(
                    user_id=self.user.id,
                    friend_id=u.id,
                    **u.dict())

    @classmethod
    def from_id(cls, user_id: int, session, update=False, gen_artist=False) -> Optional[User]:
        cache_days = 30 if not update else 0
        if not (user := session.get(User, user_id)) or update:
            if user_dict := get_user_by_id(user_id, cache_days=cache_days):
                if extra_key := set(user_dict) - set(User.__fields__):
                    logger.critical(extra_key)
                for k, v in user_dict.items():
                    if v and isinstance(v, str) and v[-1] == '万':
                        try:
                            user_dict[k] = 10000 * float(v[:-1])
                        except ValueError:
                            continue
                if not user:
                    user = User(**user_dict)
                    print(user)
                else:
                    for k, v in user_dict.items():
                        setattr(user, k, v)

        if user and gen_artist:
            artist = Artist(**user.dict())
            artist.album = 'Weibo'
            artist.user_name = user.remark or user.screen_name
            user.artist = [artist]

        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    def save_avatar(self, download_dir):
        """保存用户头像"""
        Path(download_dir).mkdir(parents=True, exist_ok=True)
        filename = f"{self.id}-{self.user.screen_name}" + \
                   Path(self.user.avatar_hd).suffix
        filepath = Path(download_dir) / filename
        if filepath.exists():
            logger.warning(f'{filepath} already exists')
        else:
            downloaded = get_url(self.user.avatar_hd).content
            filepath.write_bytes(downloaded)
            tags = {'XMP:Artist': self.user.screen_name,
                    'XMP:BlogURL': self.user.homepage}
            write_xmp(tags, filepath)
            logger.success(f'save avatar at  {filepath}')


class ArtistMethod:
    def __init__(self, user_id, session):
        self.session = session
        if not (artist := self.session.get(Artist, user_id)):
            user = UserMethod.from_id(user_id, session, gen_artist=True)
            artist = user.artist[0]
        if artist.user.remark:
            artist.user_name = artist.user.remark
        artist.age = artist.user.age
        session.add(artist)
        session.commit()
        session.refresh(artist)
        self.artist = artist

    def gen_meta(self):
        xmp = {
            'Artist': self.artist.user_name,
            'ImageCreatorID': self.artist.homepage,
            'ImageSupplierID': self.artist.id,
            'ImageSupplierName': 'Weibo'
        }
        return {'XMP:' + k: v for k, v in xmp.items()}
