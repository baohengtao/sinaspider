import json
import re

import exiftool
import pendulum
import requests
from lxml import etree
from unipath import Path

from sinaspider.config import headers
from sinaspider.helper import logger, pg

WEIBO_TABLE = 'weibo'
weibo_table = pg[WEIBO_TABLE]


class Weibo(dict):
    @classmethod
    def _fetch(cls, wb_id):
        url = f'https://m.weibo.cn/detail/{wb_id}'
        html = requests.get(url, headers=headers).text
        html = html[html.find('"status"'):]
        html = html[:html.rfind('"hotScheme"')]
        html = html[:html.rfind(',')]
        html = f'{{{html}}}'
        weibo_info = json.loads(html, strict=False)['status']
        weibo = _parse_weibo(weibo_info)
        return cls(weibo)

    @classmethod
    def from_weibo_info(cls, weibo_info):
        if weibo_info['pic_num'] > 9 or weibo_info['isLongText']:
            return cls.from_weibo_id(weibo_info['id'])
        else:
            weibo = _parse_weibo(weibo_info)
            weibo_table.upsert(weibo, ['id'])
            return cls(weibo)

    @classmethod
    def from_weibo_id(cls, wb_id):
        docu = weibo_table.find_one({'id': wb_id}) or {}
        if not docu:
            weibo = cls._fetch(wb_id)
            weibo_table.upsert(weibo, ['id'])
            return weibo
        else:
            return cls(docu)

    def print(self):

        keys = [
            'screen_name', 'id', 'text', 'location',
            'created_at', 'at_users', 'url'
        ]
        for k in keys:
            if v := self.get(k):
                logger.info(f'{k}: {v}')
        print('\n')

    def save_media(self, download_dir):
        download_dir = Path(download_dir)
        download_dir.mkdir(parents=True)
        prefix = f"{download_dir}/{self['user_id']}_{self['id']}"
        download_list = []
        # add photos urls to list
        for sn, urls in self.get('photos', dict()).items():
            for url in filter(bool, urls):
                ext = url.split('.')[-1]
                filepath = f'{prefix}_{sn}.{ext}'
                download_list.append({'url': url, 'filepath': Path(filepath)})
        # add video urls to list
        if url := self.get('video_url'):
            assert ';' not in url
            filepath = f'{prefix}.mp4'
            download_list.append({'url': url, 'filepath': Path(
                filepath), 'id': self['id'], 'user_id': self['user_id']})

        # downloading...
        if download_list:
            logger.info(
                f"{self['id']}: Downloading {len(download_list)} files to {download_dir}...")
        for dl in download_list:
            url, filepath = dl['url'], Path(dl['filepath'])
            if filepath.exists():
                logger.warning(f'{filepath} already exists..skip {url}')
                continue
            downloaded = requests.get(url, headers=headers)
            filepath.write_file(downloaded.content, "wb")
            with exiftool.ExifTool() as et:
                et.set_tags({'XMP:ImageSupplierName': 'Weibo'}, filepath)

        return download_list

    def to_xmp(self):
        xmp_info = {}
        wb_map = [
            ('bid', 'ImageUniqueID'),
            ('user_id', 'ImageSupplierID'),
            ('text', 'BlogTitle'),
            ('url', 'BlogURL'),
            ('location', 'Location'),
            ('created_at', 'DateCreated'),
        ]
        for info, xmp in wb_map:
            if v := self.get(info):
                xmp_info[xmp] = v
        xmp_info['DateCreated'] = xmp_info['DateCreated'].strftime('%Y:%m:%d %H:%M:%S.%f')
        return xmp_info


def _parse_weibo(weibo_info):
    class WeiboParser:
        def __init__(self, weibo_info):
            self.info = weibo_info
            self.wb = {}
            self.basic_info()
            self.photos_info()
            self.video_info()
            if text := weibo_info['text'].strip():
                self.selector = etree.HTML(text)
                self.selector_info()
            self.wb = {k: v for k, v in self.wb.items() if v or v == 0}

        def basic_info(self):
            id_ = self.info['id']
            bid = self.info['bid']
            user = self.info['following']
            user_id = user['id']
            screen_name = user.get('remark') or user['screen_name']
            created_at = pendulum.parse(self.info['created_at'], strict=False)
            assert created_at.is_local()
            self.wb.update(
                user_id=user_id,
                screen_name=screen_name,
                id=int(self.info['id']),
                bid=bid,
                url=f'https://weibo.com/{user_id}/{bid}',
                url_m=f'https://m.weibo.cn/detail/{id_}',
                created_at=created_at,
                source=self.info['source'],
                is_pinned=(self.info.get('title', {}).get('text') == '置顶')
            )

        def selector_info(self):
            try:
                text = self.selector.xpath('string(.)')
            except AttributeError as e:
                logger.error(self.info)
                raise e
            at_list, topics_list = [], []

            for a in self.selector.xpath('//a'):
                at_user = a.xpath('string(.)')
                if at_user[0] != '@':
                    continue
                at_user = at_user[1:]
                assert a.xpath('@href')[0][3:] == at_user
                at_list.append(at_user)

            for topic in self.selector.xpath("//span[@class='surl-text']"):
                t = topic.xpath('string(.)')
                if m := re.match('^#(.*)#$', t):
                    topics_list.append(m.group(1))

            location = ''
            location_icon = 'timeline_card_small_location_default.png'
            span_list = self.selector.xpath('//span')
            for i, span in enumerate(span_list):
                checker = span.xpath('img/@src')
                if checker and location_icon in checker[0]:
                    location = span_list[i + 1].xpath('string(.)')
                    break
            self.wb.update({
                'text': text,
                'at_users': ', '.join(at_list),
                'topics': ', '.join(topics_list),
                'location': location
            })
            return self.wb

        def photos_info(self):
            pics = self.info.get('pics', [])
            pics = [p['large']['url'] for p in pics]
            live_photo = {}
            live_photo_prefix = 'https://video.weibo.com/media/play?livephoto=//us.sinaimg.cn/'
            if pic_video := self.info.get('pic_video'):
                live_photo = pic_video.split(',')
                live_photo = [p.split(':') for p in live_photo]
                live_photo = {
                    int(sn): f'{live_photo_prefix}{path}.mov' for sn, path in live_photo}
                assert max(live_photo) < len(pics)
            self.wb['photos'] = {str(i + 1): [pic, live_photo.get(i)]
                                 for i, pic in enumerate(pics)}

        def video_info(self):
            page_info = self.info.get('page_info', {})
            if not page_info.get('type') == "video":
                return
            media_info = page_info['urls'] or page_info['media_info']
            keys = [
                'mp4_720p', 'mp4_720p_mp4', 'mp4_hd_mp4', 'mp4_hd', 'mp4_hd_url', 'hevc_mp4_hd',
                'mp4_ld_mp4', 'mp4_ld', 'stream_url_hd', 'stream_url',
                'inch_4_mp4_hd', 'inch_5_mp4_hd', 'inch_5_5_mp4_hd'
            ]
            if not set(media_info).issubset(keys):
                print(page_info)
                assert False
            urls = [v for k in keys if (v := media_info.get(k))]
            if not urls:
                logger.warning(f'no video info:==>{page_info}')
            else:
                self.wb['video_url'] = urls[0]

    wp = WeiboParser(weibo_info)
    return wp.wb
