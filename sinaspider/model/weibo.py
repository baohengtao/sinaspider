import asyncio
import itertools
import json
import re
from pathlib import Path
from typing import Iterator, Self

import pendulum
from bs4 import BeautifulSoup
from geopy.distance import geodesic
from playhouse.postgres_ext import (
    ArrayField,
    BigIntegerField,
    BooleanField,
    DateTimeTZField,
    DoubleField,
    ForeignKeyField,
    IntegerField, JSONField,
    TextField
)
from playhouse.shortcuts import model_to_dict, update_model_from_dict
from rich.prompt import Confirm

from sinaspider import console
from sinaspider.exceptions import WeiboNotFoundError
from sinaspider.helper import (
    fetcher, normalize_wb_id,
    parse_url_extension,
    round_loc
)
from sinaspider.page import Page
from sinaspider.parser import parse_weibo

from .base import BaseModel
from .user import Artist, User


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
    added_at = DateTimeTZField()
    updated_at = DateTimeTZField(null=True)
    try_update_at = DateTimeTZField(null=True)
    try_update_msg = TextField(null=True)

    class Meta:
        table_name = "weibo"

    def __repr__(slef):
        return super().__repr__()

    @classmethod
    async def from_id(cls, wb_id: int | str, update: bool = False) -> Self:
        wb_id = normalize_wb_id(wb_id)
        if update or not cls.get_or_none(id=wb_id):
            try:
                cache = await WeiboCache.from_id(wb_id, update=update)
                weibo_dict = await cache.parse()
            except WeiboNotFoundError as e:
                if not cls.get_or_none(id=wb_id):
                    raise e
                console.log(
                    f'{e}: Weibo {wb_id} is not accessible, '
                    'loading from database...',
                    style="error")
            else:
                await Weibo.upsert(weibo_dict)
        return cls.get_by_id(wb_id)

    @classmethod
    async def upsert(cls, weibo_dict: dict) -> Self:
        """
        return upserted weibo id
        """
        wid = weibo_dict['id']
        weibo_dict['username'] = User.get_by_id(
            weibo_dict['user_id']).username
        locations = weibo_dict.pop('locations', None)
        weibo_dict.pop('regions', None)
        if weibo_dict['pic_num'] > 0:
            assert weibo_dict.get('photos') or weibo_dict.get('photos_edited')

        if not (model := cls.get_or_none(id=wid)):
            cls.insert(weibo_dict).execute()
            weibo = cls.get_by_id(wid)
            await weibo.update_location()
            return weibo
        if model.location is None:
            if 'location' in weibo_dict:
                assert locations[0] is None
        else:
            assert model.location_id == weibo_dict['location_id']
        assert model.region_name == weibo_dict.get('region_name')

        model_dict = model_to_dict(model, recurse=False)
        model_dict['user_id'] = model_dict.pop('user')

        # compare photos
        assert model.photos == weibo_dict.get('photos')
        edited = model.photos_edited or []
        edited_update = weibo_dict.get('photos_edited', [])
        assert edited_update[:len(edited)] == edited
        extra = edited_update[len(edited):]

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
            assert weibo.photos_extra or list(weibo.medias())
            await weibo.update_location()
            loc_info = [weibo.location, weibo.location_id,
                        weibo.latitude, weibo.longitude]
            if not all(loc_info):
                assert loc_info == [None] * 4
        else:
            assert not list(weibo.medias())

        return weibo

    async def update_location(self):
        if self.location is None:
            assert self.location_id is None
            return
        coord = await self.get_coordinate()
        if location := await Location.from_id(self.location_id):
            if location.name != self.location:
                if location.name:
                    console.log(
                        'location name changed from'
                        f'{location.name} to {self.location}',
                        style='warning')
                location.name = self.location
                location.save()
            console.log(location)
        elif not coord:
            console.log(
                f'no coord and location found: {self.url}', style='error')
            console.log(self)
            if '_' in self.location_id:
                lng, lat = tuple(map(float, self.location_id.split('_')))
                coord = round_loc(lat, lng)
            else:
                raise ValueError(f'cannot found coord for {self.url}')

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

    async def get_coordinate(self) -> tuple[float, float] | None:
        if self.latitude:
            return round_loc(self.latitude, self.longitude)
        if art_login := self.user.following:
            token = 'from=10DA093010&s=ba74941a'
        else:
            token = 'from=10CB193010&s=BF3838D9'

        url = ('https://api.weibo.cn/2/comments/build_comments?'
               f'launchid=10000365--x&c=iphone&{token}'
               f'&id={self.id}&is_show_bulletin=2')
        status = (await fetcher.get_json(url, art_login=art_login))['status']
        if 'geo' not in status:
            console.log(
                f"no coordinates found: {self.url} ", style='error')
        elif not (geo := status['geo']):
            console.log(f'no coord found: {self.url}', style='warning')
        else:
            lat, lng = geo['coordinates']
            lat, lng = round_loc(lat, lng)
            return lat, lng

    def medias(self, filepath: Path = None,
               extra=False, no_watermark=False) -> Iterator[dict]:
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
                if i == 0 and no_watermark:
                    url = url.replace('/large/', '/oslarge/')
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
            # if (duration := self.video_duration) and duration > 600:
            #     console.log(f"video_duration is {duration})...skipping...")
            # else:
            ext = parse_url_extension(url) or '.mp4'
            assert ext == '.mp4'
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
            if v is None:
                continue
            if k in ['photos', 'attitudes_count',
                     'comments_count', 'reposts_count']:
                continue
            res[k] = v
        return "\n".join(f'{k}: {v}' for k, v in res.items())

    def highlight_social(self) -> bool:
        """
        return True if social info is found
        """
        from photosinfo.model import Girl
        text = (self.text or '').lower().replace('night', '')
        has_ins = re.findall(r'(?<![a-z])(ins|ig|instagram)(?![a-z])', text)
        has_red = re.findall(r'小红书|📕', text)
        has_awe = re.findall(r'(?<![a-z])dy(?![a-z])|抖音', text)
        if not (has_ins or has_red or has_awe):
            return False
        girl = (Girl.get_or_none(sina_id=self.user_id)
                or Girl.get_or_none(username=self.username))
        if has_ins and not (girl and girl.inst_id):
            console.log('🍬 Find Instagram info',
                        style='bold green on dark_green')
        elif has_red and not (girl and girl.red_id):
            console.log('🍬 Find 小红书 info',
                        style='bold green on dark_green')
        elif has_awe and not (girl and girl.awe_id):
            console.log('🍬 Find 抖音 info',
                        style='bold green on dark_green')
        else:
            return False
        return True

    async def liked_by(self):
        url = f'https://m.weibo.cn/api/attitudes/show?id={self.id}&page=%s'
        friends = {f.friend_id: f for f in self.user.friends}
        for page in itertools.count(1):
            js = await fetcher.get_json(
                url % page, art_login=self.user.following)
            data = js.pop('data')
            assert js == {'ok': 1, 'msg': '数据获取成功'}
            if (users := data.pop('data')) is None:
                break
            for user in users:
                if f := friends.get(user['user']['id']):
                    yield f


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

    def __str__(self):
        return super().__repr__()

    @property
    def coordinate(self) -> tuple[float, float]:
        """
        return the (lat, lng) tuple
        """
        return self.latitude, self.longitude

    @classmethod
    async def from_id(cls, location_id: str) -> Self | None:
        """
        return the Location instance from location_id
        or None if location has been deleted
        """
        if not cls.get_or_none(id=location_id):
            if info := (await cls.get_location_info_v2(location_id)
                        or await cls.get_location_info_v1p5(location_id)):
                cls.insert(info).execute()
            else:
                return
        return cls.get_by_id(location_id)

    @staticmethod
    async def get_location_info_v2(location_id):
        api = f'http://place.weibo.com/wandermap/pois?poiid={location_id}'
        info = await fetcher.get_json(api, art_login=True)
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
    async def get_location_info_v1p5(location_id: str) -> dict | None:
        url = f'https://weibo.com/p/100101{location_id}'
        url_m = ('https://m.weibo.cn/p/index?'
                 f'containerid=2306570042{location_id}')
        api = ('https://api.weibo.cn/2/cardlist?&from=10DA093010'
               f'&c=iphone&s=ba74941a&containerid=2306570042{location_id}')
        js = await fetcher.get_json(api, art_login=True)
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


class WeiboCache(BaseModel):
    id = BigIntegerField(primary_key=True, unique=True)
    user_id = BigIntegerField(index=True)
    timeline_web = JSONField(null=True)
    page_web = JSONField(null=True)
    timeline_weico = JSONField(null=True)
    page_weico = JSONField(null=True)
    liked_weico = JSONField(null=True)
    hist_mblogs = JSONField(null=True)
    edit_count = IntegerField()
    added_at = DateTimeTZField()
    updated_at = DateTimeTZField(null=True)

    def __str__(self):
        return super().__repr__()

    @classmethod
    async def from_id(cls, weibo_id, update=False) -> Self:
        weibo_id = normalize_wb_id(weibo_id)
        if not update and (cache := cls.get_or_none(id=weibo_id)):
            return cache
        try:
            mblog = await get_mblog_from_web(weibo_id)
        except WeiboNotFoundError as e:
            console.log(e, style='error')
            raise
        return await cls.upsert(mblog)

    @staticmethod
    def preprocess_mblog(mblog):
        if 'pic_ids' not in mblog:
            assert 'weico' in mblog['mblog_from']
            p = [u for u in mblog['url_struct'] if 'pic_ids' in u]
            assert len(p) == 1
            p = p[0]
            assert p | mblog == mblog | p
            mblog |= p
        return mblog

    @classmethod
    async def upsert(cls, mblog: dict) -> Self:
        mblog = cls.preprocess_mblog(mblog)
        assert len(mblog['pic_ids']) == min(mblog['pic_num'], 9)
        need_page = (mblog['pic_num'] > 9) or mblog['isLongText']

        weibo_id = mblog['id']
        user_id = mblog['user']['id']
        edit_count = mblog.get('edit_count', 0)
        mblog_from = mblog['mblog_from']
        if cache := WeiboCache.get_or_none(id=weibo_id):
            assert cache.user_id == user_id
            assert bool(cache.edit_count) == bool(cache.hist_mblogs)
            assert edit_count >= cache.edit_count
            if cache.edit_count == edit_count and getattr(cache, mblog_from):
                if need_page:
                    assert getattr(
                        cache, mblog_from.replace('timeline', 'page'))
                setattr(cache, mblog_from, mblog)
                cache.updated_at = pendulum.now()
                cache.save()
                return cache
        row = {
            'id': weibo_id,
            mblog_from: mblog,
            "edit_count": edit_count,
            'user_id': user_id,
        }
        if edit_count > (cache.edit_count if cache else 0):
            console.log(
                f'fetching hist_mblogs: https://weibo.com/{user_id}/{weibo_id}')
            row['hist_mblogs'] = await get_hist_mblogs(weibo_id, edit_count)

        if need_page and 'page' not in mblog_from:
            console.log(
                f'fetching weibo page: https://weibo.com/{user_id}/{weibo_id}')
            if 'weico' in mblog_from:
                row['page_weico'] = await get_mblog_from_weico(weibo_id)
            else:
                row['page_web'] = await get_mblog_from_web(weibo_id)
        if cache:
            update_model_from_dict(cache, row)
            cache.updated_at = pendulum.now()
            cache.save()
        else:
            row['added_at'] = pendulum.now()
            cls.insert(row).execute()
        return cls.get_by_id(weibo_id)

    async def parse(self, weico_first=False):
        assert bool(self.edit_count) == bool(self.hist_mblogs)
        if hist_mblogs := self.hist_mblogs:
            hist_mblogs = self.hist_mblogs['mblogs']
        web = self.page_web or self.timeline_web
        weico = self.page_weico or self.timeline_weico or self.liked_weico
        info = (weico or web) if weico_first else (web or weico)
        weibo_dict = await parse_weibo(info, hist_mblogs)
        assert 'updated_at' not in weibo_dict
        assert 'added_at' not in weibo_dict
        if self.updated_at:
            weibo_dict['updated_at'] = self.updated_at
        weibo_dict['added_at'] = self.added_at
        return weibo_dict


async def get_hist_mblogs(weibo_id: int | str, edit_count: int) -> list[dict]:
    s = '0726b708' if fetcher.art_login else 'c773e7e0'
    edit_url = ("https://api.weibo.cn/2/cardlist?c=weicoabroad"
                f"&containerid=231440_-_{weibo_id}"
                f"&page=%s&s={s}"
                )
    all_cards = []
    for page in itertools.count(1):
        js = await fetcher.get_json(edit_url % page)
        all_cards += js['cards']
        if len(all_cards) >= edit_count + 1:
            assert len(all_cards) == edit_count + 1
            break
        elif not js['cards']:
            assert len(all_cards) == edit_count
            break
    mblogs = []
    for card in all_cards[::-1]:
        card = card['card_group']
        assert len(card) == 1
        card = card[0]
        if card['card_type'] != 9:
            continue
        mblogs.append(card['mblog'])
    return dict(mblogs=mblogs, all_cards=all_cards)


async def get_mblog_from_weico(id):
    if fetcher.art_login is None:
        await fetcher.toggle_art(True)
    s = '2a2eb444' if fetcher.art_login else 'c2c66eee'
    id = normalize_wb_id(id)
    url = ('https://api.weibo.cn/2/statuses/show?'
           f"&c=weicoabroad&from=12D9393010&s={s}"
           f'&id={id}&isGetLongText=1'
           )
    mblog = await fetcher.get_json(url)
    mblog['mblog_from'] = 'page_weico'
    return mblog


async def get_mblog_from_web(weibo_id: str | int) -> dict:
    url = f'https://m.weibo.cn/detail/{weibo_id}'
    while True:
        text = (await fetcher.get(url)).text
        soup = BeautifulSoup(text, 'html.parser')
        if soup.title.text == '微博-出错了':
            assert (err_msg := soup.body.p.text.strip())
            if err_msg in ['请求超时', 'Redis执行失败']:
                console.log(
                    f'{err_msg} for {url}, sleeping 60 secs...',
                    style='error')
                await asyncio.sleep(60)
                continue
            else:
                raise WeiboNotFoundError(err_msg, url)
        break
    rec = re.compile(
        r'.*var \$render_data = \[(.*)]\[0] \|\| \{};', re.DOTALL)
    html = rec.match(text).groups(1)[0]
    weibo_info = json.loads(html, strict=False)['status']
    console.log(f"{weibo_id} fetched in online.")
    pic_num = len(weibo_info['pic_ids'])
    if not weibo_info['pic_num'] == pic_num:
        console.log(f'actually there are {pic_num} pictures for {url} '
                    f'but pic_num is {weibo_info["pic_num"]}',
                    style='error')
        weibo_info['pic_num'] = pic_num
    weibo_info['mblog_from'] = "page_web"

    return weibo_info


class WeiboLiked(BaseModel):
    weibo_id = BigIntegerField()
    weibo_by = BigIntegerField()
    pic_num = IntegerField()
    user = ForeignKeyField(User, backref='weibos_liked')
    order_num = IntegerField()
    added_at = DateTimeTZField(default=pendulum.now)
    username = TextField()
    created_at = DateTimeTZField()

    def __str__(self):
        return super().__repr__()

    class Meta:
        table_name = "liked"
        indexes = (
            (('user_id', 'order_num'), True),
            (('weibo_id', 'user_id'), True),
        )


class WeiboMissed(BaseModel):
    bid = TextField(primary_key=True, unique=True)
    user = ForeignKeyField(User, backref='weibos_missed')
    username = TextField()
    created_at = DateTimeTZField()
    text = TextField(null=True)
    region_name = TextField(null=True)
    location = TextField(null=True)
    latitude = DoubleField(null=True)
    longitude = DoubleField(null=True)
    try_update_at = DateTimeTZField(null=True)
    try_update_msg = TextField(null=True)
    visible = BooleanField(null=True)

    uid_username = {a.user_id: a.username for a in Artist}
    uid_visible = {}

    def __str__(self):
        return super().__repr__()

    @classmethod
    async def update_missing(cls, num=50):
        query = (cls.select()
                 .order_by(cls.user, cls.created_at)
                 .where(cls.try_update_at.is_null()))
        query_recent = query.where(
            cls.created_at > pendulum.now().subtract(months=6))
        query_first = query_recent.where(
            cls.created_at < pendulum.now().subtract(months=5))
        query = (query_first or query_recent or query.where(
            cls.visible.is_null()) or query)
        if not query:
            raise ValueError('no missing to update')
        usernames = {m.username for m in query[:num]}
        for i, missing in enumerate(query.where(cls.username.in_(usernames)),
                                    start=1):
            missing: cls
            console.log(f'🎠 Working on {i}/{len(query)}', style='notice')
            await missing.update_missing_single()
        console.log(f'updated {i} missing weibos', style='warning')

    async def update_missing_single(self):
        if self.created_at > pendulum.now().subtract(months=6):
            self.visible = True
            self.save()
        else:
            if self.user_id not in self.uid_visible:
                console.log(f'getting visibility of {self.username}...')
                self.uid_visible[self.user_id] = await Page(
                    self.user_id).get_visibility()
            self.visible = self.uid_visible[self.user_id]
            self.save()

        await fetcher.toggle_art(self.user.following)
        assert not Weibo.get_or_none(bid=self.bid)
        try:
            weibo = await Weibo.from_id(self.bid)
        except WeiboNotFoundError as e:
            self.try_update_at = pendulum.now()
            self.try_update_msg = str(e.err_msg)
            self.save()
            console.log(e, style='error')
            console.log(self)
            console.log()
            assert not Weibo.get_or_none(bid=self.bid)
            return
        except Exception:
            console.log(
                f'error for https://weibo.com/{self.user_id}/{self.bid}',
                style='error')
            if Weibo.get_or_none(bid=self.bid):
                Weibo.delete_instance()
            raise
        try:
            assert self.visible is True
            assert self.bid == weibo.bid
            assert self.user == weibo.user
            assert self.username == weibo.username
            if self.created_at != weibo.created_at:
                if (self.created_at.timestamp()
                        - weibo.created_at.timestamp()) == 8*3600:
                    console.log(
                        'created_at changed from '
                        f'{self.created_at} to {weibo.created_at}',
                        style='error')
                else:
                    assert False

            if self.region_name:
                assert self.region_name == weibo.region_name
            if self.latitude:
                assert weibo.location and weibo.location_id
                assert weibo.latitude and weibo.longitude
                l1 = (weibo.location, weibo.latitude, weibo.longitude)
                l2 = (self.location, self.latitude,
                      self.longitude)
                if l1 != l2:
                    console.log(f'location changed from {l2} to {l1}',
                                style='warning')
        except Exception:
            console.log(f'error for {weibo.url}', style='error')
            weibo.delete_instance()
            raise
        else:
            console.log(f'🎉 sucessfuly updated {weibo.url}')
            console.log(weibo)
            self.delete_instance()
            console.log()

    @classmethod
    def add_missing(cls):
        from photosinfo.model import Photo
        query = (WeiboMissed.select()
                 .where(WeiboMissed.bid.in_([w.bid for w in Weibo]))
                 .order_by(WeiboMissed.user_id))
        for missed in query:
            console.log('find following in weibo, deleting...')
            console.log(missed, '\n')
            missed.delete_instance()
        skip1 = {w.bid for w in Weibo}
        skip2 = {w.bid for w in cls}
        assert not (skip1 & skip2)
        skip = skip1 | skip2
        photo_query = (Photo.select()
                       .where(Photo.image_supplier_name == 'Weibo')
                       .where(Photo.image_unique_id.is_null(False))
                       .order_by(Photo.uuid)
                       )
        collections = {}
        for p in photo_query:
            if (bid := p.image_unique_id) in skip:
                continue
            if ((bid not in collections) or (
                    not collections[bid]['latitude'] and p.latitude)):
                collections[bid] = cls.extract_photo(p)

        if collections:
            console.log(
                f'inserting {len(collections)} weibos', style='warning')
            raise ValueError('there should be no missing now')
            WeiboMissed.insert_many(collections.values()).execute()
        else:
            console.log('no additional missing weibo found')
        bids_lib = {p.image_unique_id for p in photo_query}
        if query := (cls.select()
                     .where(cls.bid.not_in(bids_lib)).order_by(cls.user)):
            console.log(
                f'found {len(query)} weibos to delete', style='warning')
            console.log(list(query))
            if Confirm.ask('delete?'):
                for missing in query:
                    missing.delete_instance()

    @classmethod
    def extract_photo(cls, photo: 'Photo') -> dict:
        """
        return: {'user_id': 6619193364,
                    'bid': 'H0SrPwpyF',
                    'created_at': DateTime(2018, 11, 3, 2, 12, 47, tzinfo=Timezone('Asia/Shanghai')),
                    'text': '终于熬夜把考题给录进去了 希望不要出错 睡啦 📍北京·清华大学紫荆学生公寓十五号楼',
                    'regin_name': None,
                    'location': '北京·清华大学紫荆学生公寓十五号楼',
                    'username': 'cooper_math'}
        """
        photo_dict = model_to_dict(photo)
        pop_keys = [
            'uuid', 'row_created', 'hidden', 'filesize',
            'date', 'date_added', 'live_photo', 'with_place', 'ismovie',
            'favorite', 'album', 'title', 'description', 'filename',
            'series_number', 'image_creator_name', 'filepath', 'edited',
            'img_url', ]
        for k in pop_keys:
            photo_dict.pop(k)
        assert photo_dict.pop('image_supplier_name') == 'Weibo'
        timestamp = int(photo_dict.pop('date_created').timestamp())
        text, *region_name = (photo_dict.pop('blog_title') or '').split('发布于')
        if region_name:
            assert len(region_name) == 1
            region_name = region_name[0].strip()
        else:
            region_name = None
        extracted = {
            'user_id': (user_id := int(photo_dict.pop('image_supplier_id'))),
            'username': (username := cls.uid_username[user_id]),
            'bid': (bid := photo_dict.pop('image_unique_id')),
            'created_at': pendulum.from_timestamp(timestamp, tz='local'),
            'text': text.strip() or None,
            'region_name': region_name,
            'location': photo_dict.pop('location'),
            'latitude': (lat := photo_dict.pop('latitude')),
            'longitude': (lng := photo_dict.pop('longitude')),
        }

        assert photo_dict.pop(
            'image_creator_id') == f'https://weibo.com/u/{user_id}'

        assert photo_dict.pop('geography') == (f'{lat} {lng}' if lat else None)

        if blog_url := photo_dict.pop('blog_url'):
            assert blog_url == f'https://weibo.com/{user_id}/{bid}'
        assert photo_dict.pop('artist') == username
        assert not photo_dict

        return extracted

    @classmethod
    def add_missing_from_weiboliked(cls):
        from photosinfo.model import Photo

        from .config import UserConfig
        uids = [u.user_id for u in UserConfig if u.photos_num > 0]
        query = (Photo.select()
                 .where(Photo.image_supplier_id.in_(uids))
                 .where(Photo.image_supplier_name == 'WeiboLiked')
                 )
        if not query:
            return
        collections = [cls.extract_weiboliked(p) for p in query]
        collections = {c['bid']: c for c in collections}
        assert not (set(collections) & {w.bid for w in Weibo})
        console.log(
            f'inserting {len(collections)} weiboliked to WeiboMissed', style='warning')
        collections = collections.values()
        for c in collections:
            console.log(c, '\n')
            c['username'] = cls.uid_username[c['user_id']]
        cls.insert_many(collections).execute()
        return collections

    @staticmethod
    def extract_weiboliked(photo: 'Photo') -> dict:
        import re

        from sinaspider.helper import encode_wb_id
        photo_dict = model_to_dict(photo)
        pop_keys = [
            'uuid', 'row_created', 'date', 'date_added',  'series_number',
            'filepath', 'filesize', 'filename', 'image_creator_name', 'artist',
            'edited', 'live_photo', 'with_place', 'ismovie', 'hidden',
            'favorite', 'album', 'title', 'description',
        ]
        for k in pop_keys:
            photo_dict.pop(k)
        assert photo_dict.pop('image_supplier_name') == 'WeiboLiked'
        for k in ['image_creator_id',
                  'location', 'latitude', 'longitude', 'geography'
                  ]:
            assert photo_dict.pop(k) is None
        text, *region_name = (photo_dict.pop('blog_title') or '').split('发布于')
        if region_name:
            assert len(region_name) == 1
            region_name = region_name[0].strip()
        else:
            region_name = None
        pattern = r'https://weibo\.com/(\d+)/([\w\d]+)'
        user_id, weibo_id = re.match(
            pattern, photo_dict.pop('blog_url')).groups()
        if image_unique_id := photo_dict.pop('image_unique_id'):
            assert image_unique_id == weibo_id
        timestamp = int(photo_dict.pop('date_created').timestamp())

        assert int(photo_dict.pop('image_supplier_id')) == int(user_id)
        assert not photo_dict
        if weibo_id.isdigit():
            weibo_id = encode_wb_id(weibo_id)
        return {
            'user_id': int(user_id),
            'bid': weibo_id,
            'created_at': pendulum.from_timestamp(timestamp, tz='local'),
            'text': text.replace('\u200b', '').strip(),
            'region_name': region_name,
        }

    def gen_meta(self, sn: str | int = '', url: str = "") -> dict:
        title = (self.text or "").strip()
        if self.region_name:
            title += f" 发布于{self.region_name}"
        xmp_info = {
            "ImageUniqueID": self.bid,
            "ImageSupplierID": self.user_id,
            "ImageSupplierName": "Weibo",
            "ImageCreatorName": self.username,
            "BlogTitle": title.strip(),
            "BlogURL": f'https://weibo.com/{self.user_id}/{self.bid}',
            "Location": self.location,
            "DateCreated": (self.created_at +
                            pendulum.Duration(microseconds=int(sn or 0))),
            "SeriesNumber": sn,
            "URLUrl": url
        }
        xmp_info["DateCreated"] = xmp_info["DateCreated"].strftime(
            "%Y:%m:%d %H:%M:%S.%f").strip('0').strip('.')
        res = {"XMP:" + k: v for k, v in xmp_info.items() if v}
        if self.location:
            if self.latitude:
                res['WeiboLocation'] = (self.latitude, self.longitude)
            else:
                location = Location.get(name=self.location)
                res['WeiboLocation'] = location.coordinate
        return res
