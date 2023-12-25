import itertools
import json
import re
import time
import warnings

import bs4
import pendulum
from bs4 import BeautifulSoup

from sinaspider import console
from sinaspider.exceptions import WeiboNotFoundError
from sinaspider.helper import encode_wb_id, fetcher, parse_loc_src


class WeiboParser:
    """用于解析原始微博内容."""

    def __init__(self, weibo_info: dict | int | str):
        if isinstance(weibo_info, dict):
            if 'pic_ids' not in weibo_info:
                weibo_info = weibo_info['id']
                console.log(f'pic_ids not found for weibo {weibo_info},'
                            'fetching online...', style='warning')
            elif weibo_info['pic_num'] > len(weibo_info['pic_ids']):
                assert weibo_info['pic_num'] > 9
                weibo_info = weibo_info['id']
            elif weibo_info['isLongText'] and (
                    weibo_info['mblog_from'] != 'liked_weico'):
                ends = f'<a href=\"/status/{weibo_info["id"]}\">全文</a>'
                assert weibo_info['text'].endswith(ends)
                weibo_info = weibo_info['id']

        if isinstance(weibo_info, (int, str)):
            self.info = self._fetch_info(weibo_info)
        else:
            self.info = weibo_info
        self.id = self.info['id']
        self.pic_num = self.info['pic_num']
        self.edit_count = self.info.get('edit_count', 0)
        self.hist_mblogs = None
        self.edit_at = None
        if self.edit_count:
            console.log(
                f'{self.id} edited in {self.edit_count} times, finding hist_mblogs...')
            self.hist_mblogs = self.get_hist_mblogs()
            if len(self.hist_mblogs) > 1:
                self.edit_at = pendulum.from_format(
                    self.hist_mblogs[-1]['edit_at'],
                    'ddd MMM DD HH:mm:ss ZZ YYYY')
                assert self.edit_at.is_local()

        assert self.pic_num <= len(self.info['pic_ids'])
        if self.pic_num < len(self.info['pic_ids']):
            console.log(
                f"pic_num < len(pic_ids) for {self.id}",
                style="warning")

    @staticmethod
    def _fetch_info(weibo_id: str | int) -> dict:
        url = f'https://m.weibo.cn/detail/{weibo_id}'
        while True:
            text = fetcher.get(url).text
            soup = BeautifulSoup(text, 'html.parser')
            if soup.title.text == '微博-出错了':
                assert (err_msg := soup.body.p.text.strip())
                if err_msg in ['请求超时', 'Redis执行失败']:
                    console.log(
                        f'{err_msg} for {url}, sleeping 60 secs...',
                        style='error')
                    time.sleep(60)
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

    def get_hist_mblogs(self) -> list[dict]:
        s = '0726b708' if fetcher.art_login else 'c773e7e0'
        edit_url = ("https://api.weibo.cn/2/cardlist?c=weicoabroad"
                    f"&containerid=231440_-_{self.id}"
                    f"&page=%s&s={s}"
                    )
        all_cards = []
        for page in itertools.count(1):
            js = fetcher.get(edit_url % page).json()
            all_cards += js['cards']
            if len(all_cards) >= self.edit_count + 1:
                assert len(all_cards) == self.edit_count + 1
                break
        mblogs = []
        for card in all_cards[::-1]:
            card = card['card_group']
            assert len(card) == 1
            card = card[0]
            if card['card_type'] != 9:
                continue
            mblogs.append(card['mblog'])
        return mblogs

    def parse(self):
        weibo = self.basic_info()
        if video := self.video_info():
            weibo |= video
        weibo |= self.photos_info_with_hist()
        weibo |= self.location_info_with_hist() or {}
        weibo |= self.text_info(self.info['text'])

        weibo['pic_num'] = self.pic_num
        weibo['edit_count'] = self.edit_count
        weibo['edit_at'] = self.edit_at
        weibo['update_status'] = 'updated'
        weibo = self.post_process(weibo)
        weibo = {k: v for k, v in weibo.items() if v not in ['', [], None]}
        weibo['has_media'] = bool(weibo.get('video_url') or weibo.get(
            'photos') or weibo.get('photos_edited'))

        self.weibo = weibo

        return weibo.copy()

    @staticmethod
    def post_process(weibo: dict) -> dict:
        # get regions and location which parsed from history
        regions = weibo.get('regions')
        locations = weibo.get('locations')
        assert bool(regions) == bool(locations)
        if not regions:
            return weibo

        # compare region
        if weibo.get('region_name') != regions[-1]:
            console.log(
                '>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>',
                style='warning')
            console.log('region not match: ')
            console.log(f'regions in hist: {regions}')
            console.log(f'region in weibo: {weibo.get("region_name")}')
            console.log('<'*50, style='warning')

        # compare location
        if not weibo.get('location'):
            if locations[-1] and ('weico' not in weibo.get('mblog_from', '')):
                assert 'location' not in locations[-1]
                console.log(
                    '>>>>>>>>>>>location not found but geo is in there<<<<<<<<<<<<<<',
                    style='warning')
                console.log(locations[-1])
                console.log('>'*60, style='warning')

        else:
            assert weibo['location'] == locations[-1]['location']
            assert weibo['location_id'] == locations[-1]['location_id']

        rl = None
        has_geo = False
        for reginon, location in zip(regions, locations):
            if location is None:
                continue
            if rl is None:
                rl = (reginon, location)
            if location.get('latitude'):
                if location.get('location'):
                    rl = (reginon, location)
                    break
                else:
                    has_geo = True

        if rl:
            region, location = rl
            assert not has_geo or 'latitude' in location
            weibo |= location
            weibo.pop('title', None)
            if 'location' not in location:
                assert all('location' not in loc for loc in locations)
                assert 'location' not in weibo
                console.log(
                    '>>>>no location found, using title instead<<<<<',
                    style='warning')
                console.log(location)
                console.log(
                    '<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<',
                    style='warning')
                weibo['location'] = location['title']
        else:
            for region in regions:
                if region:
                    break
            location = locations[0]
            assert location is None
        weibo['region_name'] = region
        if loc := weibo.get('location'):
            text = weibo['text'].removesuffix('📍')
            assert not text.endswith('📍')
            text += f' 📍{loc}'
            weibo['text'] = text.strip()

        rs, ls = [], []
        for r, l in zip(regions, locations):
            if r not in rs:
                rs.append(r)
            if l not in ls:
                ls.append(l)
        if len(rs) > 1:
            console.log(
                '>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>',
                style='warning')
            console.log(f'multi region found: {rs},  {region} is chosen')
            console.log(
                '<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<',
                style='warning')
        if len(ls) > 1:
            console.log('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>',
                        style='warning')
            console.log(ls)
            console.log(
                f'multi location found,  {location} is chosen')
            console.log('<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<',
                        style='warning')
        return weibo

    def photos_info_with_hist(self) -> dict:

        final_photos = self.photos_info(self.info)
        if not self.hist_mblogs:
            return {'photos': final_photos}

        res = []

        for mblog in self.hist_mblogs:
            try:
                ps = self.photos_info(mblog)
            except KeyError:
                if '抱歉，此微博已被删除。查看帮助：' not in mblog['text']:
                    console.log(
                        f'parse photo info with hist failed for weibo {self.id}',
                        style='error')
                continue
            res.append(ps)
        photos = []
        for ps in res:
            for p in ps:
                if p not in photos:
                    photos.append(p)
        if not set(final_photos).issubset(set(photos)):
            console.log(
                '>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>',
                style='warning')
            console.log('photos not match: ')
            console.log(f'photos in hist which is used is: {photos}')
            console.log(f'photos in weibo: {final_photos}')
            console.log('<'*50, style='warning')
        if len(photos) > len(final_photos):
            console.log(
                '🎉 the pic num increase from '
                f'{len(final_photos)} to {len(photos)}',
                style='notice')
        assert res
        photos, edited = photos[:len(res[0])], photos[len(res[0]):]

        return dict(
            photos=photos, photos_edited=edited,)

    def location_info_with_hist(self) -> dict | None:
        if not self.hist_mblogs:
            return
        regions = []
        for mblog in self.hist_mblogs:
            if region_name := mblog.get('region_name'):
                region_name = region_name.removeprefix('发布于').strip()
            if region_name == '其他':
                region_name = None
            regions.append(region_name)

        locations_from_url = []
        for mblog in self.hist_mblogs:
            url_struct = mblog.get('url_struct', [])
            pos = [u for u in url_struct if u.get('object_type') == 'place']
            if not pos:
                locations_from_url.append(None)
                continue
            assert len(pos) == 1
            pos = pos[0]
            page_id = pos['page_id']
            assert page_id.startswith('100101')
            location_id = page_id.removeprefix('100101')
            location = pos['url_title']
            locations_from_url.append({
                'location': location,
                'location_id': location_id,
            })

        locations = []
        for mblog in self.hist_mblogs:
            # parse tag_struct
            tag_struct = [s for s in mblog.get(
                'tag_struct', []) if s.get('otype') == 'place']
            assert len(tag_struct) <= 1
            if tag_struct:
                tag_struct = tag_struct[0]
                location_id: str = tag_struct['oid']
                assert location_id.startswith('1022:100101')
                location_id = location_id.removeprefix('1022:100101')
                location = tag_struct['tag_name']
                tag_struct = {
                    'location': location,
                    'location_id': location_id,
                }

            # parse geo
            if geo := mblog.get('geo'):
                assert geo['type'] == 'Point'
                lat, lng = geo['coordinates']
                assert list(geo.keys()) == ['type', 'coordinates']
                geo = {
                    'latitude': lat,
                    'longitude': lng,
                }

            # parse annotations
            annotations = [a for a in mblog.get(
                'annotations', []) if 'place' in a]
            assert len(annotations) <= 1
            if annotations:
                annotations = annotations[0]['place']
                annotations = {
                    'title': annotations['title'],
                    'location_id': annotations['poiid'],
                }

            # merge annotations to tag_struct or geo
            if tag_struct:
                assert annotations
                assert tag_struct['location_id'] == annotations['location_id']
                tag_struct |= annotations
            elif geo:
                assert annotations
                geo |= annotations
            else:
                locations.append(annotations or None)
                continue

            if tag_struct and geo:
                locations.append(tag_struct | geo)
            elif not geo:
                locations.append(tag_struct)
            else:
                locations.append(geo)

        assert len(locations) == len(
            locations_from_url) == len(self.hist_mblogs)
        if locations == [None] * len(locations):
            locations = locations_from_url
        else:
            assert locations_from_url == [None] * len(locations)

        return dict(locations=locations, regions=regions)

    def basic_info(self) -> dict:
        user = self.info['user']
        created_at = pendulum.from_format(
            self.info['created_at'], 'ddd MMM DD HH:mm:ss ZZ YYYY')
        assert created_at.is_local()
        if region_name := self.info.get('region_name'):
            region_name = region_name.removeprefix('发布于').strip()
        assert 'retweeted_status' not in self.info
        weibo = dict(
            user_id=(user_id := user['id']),
            id=(id_ := int(self.info['id'])),
            bid=(bid := encode_wb_id(id_)),
            username=user.get('remark') or user['screen_name'],
            url=f'https://weibo.com/{user_id}/{bid}',
            url_m=f'https://m.weibo.cn/detail/{bid}',
            created_at=created_at,
            source=BeautifulSoup(
                self.info['source'].strip(), 'html.parser').text,
            region_name=region_name,
            mblog_from=self.info.get('mblog_from')
        )
        for key in ['reposts_count', 'comments_count', 'attitudes_count']:
            if (v := self.info[key]) == '100万+':
                v = 1000000
            weibo[key] = v
        return weibo

    @staticmethod
    def photos_info(info: dict) -> list[str]:
        if info['pic_num'] == 0:
            return []
        if 'pic_infos' in info:
            pic_infos = [info['pic_infos'][pic_id]
                         for pic_id in info['pic_ids']]
            photos = [[pic_info['largest']['url'], pic_info.get('video', '')]
                      for pic_info in pic_infos]
        elif pics := info.get('pics'):
            pics = pics.values() if isinstance(pics, dict) else pics
            pics = [p for p in pics if 'pid' in p]
            photos = [[pic['large']['url'], pic.get('videoSrc', '')]
                      for pic in pics]
        elif page_info := info.get('page_info'):
            assert info['pic_num'] == 1
            page_pic = page_info['page_pic']
            url = page_pic if isinstance(
                page_pic, str) else page_pic['url']
            photos = [[url, '']]
        else:
            assert info['pic_num'] == 1
            for struct in info['url_struct']:
                if 'pic_infos' in struct:
                    break
            pic_infos = [struct['pic_infos'][pic_id]
                         for pic_id in struct['pic_ids']]
            photos = [[pic_info['largest']['url'], pic_info.get('video', '')]
                      for pic_info in pic_infos]
            info = struct

        for p in photos:
            if p[0].endswith('.gif'):
                if p[1] and ('https://video.weibo.com/media/play?fid=' not in p[1]):
                    assert "://g.us.sinaimg.cn/" in p[1]
                p[1] = ''
            else:
                p[1] = p[1].replace("livephoto.us.sinaimg.cn", "us.sinaimg.cn")
        assert len(photos) == len(info['pic_ids'])
        photos = ["🎀".join(p).strip("🎀") for p in photos]
        return photos

    def video_info(self) -> dict | None:
        weibo = {}
        page_info = self.info.get('page_info', {})
        if not page_info.get('type') == "video":
            return
        if (urls := page_info['urls']) is None:
            console.log('cannot get video url', style='error')
            return
        keys = ['mp4_1080p_mp4', 'mp4_720p_mp4',
                'mp4_hd_mp4', 'mp4_ld_mp4']
        for key in keys:
            if url := urls.get(key):
                weibo['video_url'] = url
                break
        else:
            console.log(f'no video info:==>{page_info}', style='error')
            raise ValueError('no video info')

        weibo['video_duration'] = page_info['media_info']['duration']
        return weibo

    @staticmethod
    def text_info(text) -> dict:
        hypertext = text.replace('\u200b', '').strip()
        topics = []
        at_users = []
        location_collector = []
        with warnings.catch_warnings(
            action='ignore',
            category=bs4.MarkupResemblesLocatorWarning
        ):
            soup = BeautifulSoup(hypertext, 'html.parser')
        for child in list(soup.contents):
            if child.name != 'a':
                continue
            if m := re.match('^#(.*)#$', child.text):
                topics.append(m.group(1))
            elif child.text[0] == '@':
                user = child.text[1:]
                assert child.attrs['href'][3:] == user
                at_users.append(user)
            elif len(child) == 2:
                url_icon, surl_text = child.contents
                if not url_icon.attrs['class'] == ['url-icon']:
                    continue
                _icn = 'timeline_card_small_location_default.png'
                _icn_video = 'timeline_card_small_video_default.png'
                if _icn in url_icon.img.attrs['src']:

                    assert surl_text.attrs['class'] == ['surl-text']
                    if ((loc := [surl_text.text, child.attrs['href']])
                            not in location_collector):
                        location_collector.append(loc)
                    child.decompose()
                elif _icn_video in url_icon.img.attrs['src']:
                    child.decompose()
        location, location_id = None, None
        if location_collector:
            assert len(location_collector) == 1
            location, href = location_collector[-1]
            pattern1 = r'^http://weibo\.com/p/100101([\w\.\_-]+)$'
            pattern2 = (r'^https://m\.weibo\.cn/p/index\?containerid='
                        r'2306570042(\w+)')
            if match := (re.match(pattern1, href)
                         or re.match(pattern2, href)):
                location_id = match.group(1)
            else:
                location_id = parse_loc_src(href)
        res = {
            'at_users': at_users,
            'topics': topics,
            'location': location,
            'location_id': location_id,
        }
        text = soup.get_text(' ', strip=True)
        assert text == text.strip()
        res['text'] = text
        return {k: v for k, v in res.items() if v is not None}
