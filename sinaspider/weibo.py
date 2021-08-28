import json
import re
from pathlib import Path
from typing import Union

import pendulum
from bs4 import BeautifulSoup
from lxml import etree

from sinaspider.helper import logger, pg, get_url, get_json, pause

WEIBO_TABLE = 'weibo'
weibo_table = pg[WEIBO_TABLE]


class Weibo(dict):

    @classmethod
    def from_weibo_id(cls, wb_id):
        """从数据库获取微博信息, 若不在其中, 则尝试从网络获取, 并将获取结果存入数据库"""
        assert isinstance(wb_id, int), wb_id
        docu = (weibo_table.find_one(id=wb_id)
                or weibo_table.find_one(retweet_id=id)
                or {})
        if not docu:
            weibo = get_weibo_by_id(wb_id)
            weibo_table.upsert(weibo, ['id'])
            return weibo
        else:
            return cls(docu)

    def print(self):
        """打印微博信息"""
        keys = [
            'screen_name', 'id', 'text', 'location',
            'created_at', 'at_users', 'url'
        ]
        for k in keys:
            if v := self.get(k):
                logger.info(f'{k}: {v}')
        print('\n')

    def save_media(self, download_dir: Union[str, Path], write_xmp: bool = False) -> list:
        """
        保存微博图片/视频到指定目录

        Args:
            download_dir (Union[str|Path]): 文件保存目录
            write_xmp (bool, optional): 是否将微博信息写入文件, 默认不写入. (该功能需安装exiftool)

        Returns:
            list: 返回下载列表
        """

        subdir = 'retweet' if 'retweet_by' in self else 'original'
        download_dir = Path(download_dir) / subdir
        download_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{download_dir}/{self['user_id']}_{self['id']}"
        download_list = []
        # add photos urls to list
        for sn, urls in self.get('photos', dict()).items():
            for url in filter(bool, urls):
                ext = url.split('.')[-1]
                filepath = f'{prefix}_{sn}.{ext}'
                download_list.append({
                    'url': url,
                    'filepath': Path(filepath),
                    'xmp_info': self.to_xmp(sn)})
        # add video urls to list
        if url := self.get('video_url'):
            assert ';' not in url
            filepath = f'{prefix}.mp4'
            download_list.append({
                'url': url,
                'filepath': Path(filepath),
                'xmp_info': self.to_xmp()})

        # downloading...
        if download_list:
            logger.info(
                f"{self['id']}: Downloading {len(download_list)} files to {download_dir}...")
        for dl in download_list:
            url, filepath = dl['url'], Path(dl['filepath'])
            if filepath.exists():
                logger.warning(f'{filepath} already exists..skip {url}')
                continue
            downloaded = get_url(url).content
            filepath.write_bytes(downloaded)
            if write_xmp:
                from exiftool import ExifTool
                with ExifTool() as et:
                    xmp_info = {'XMP:' + k: v for k, v in dl['xmp_info'].items()}
                    et.set_tags(xmp_info, str(filepath))

        return download_list

    def to_xmp(self, sn=0) -> dict:
        """
        生产图片元数据

        Args:
            sn ( , optional): 图片序列SeriesNumber信息(即图片的次序)

        Returns:
            dict: 图片元数据
        """
        xmp_info = {}
        wb_map = [
            ('bid', 'ImageUniqueID'),
            ('user_id', 'ImageSupplierID'),
            ('screen_name', 'ImageSupplierName'),
            ('text', 'BlogTitle'),
            ('url', 'BlogURL'),
            ('location', 'Location'),
            ('created_at', 'DateCreated'),
        ]
        for info, xmp in wb_map:
            if v := self.get(info):
                xmp_info[xmp] = v
        xmp_info['DateCreated'] = xmp_info['DateCreated'].strftime(
            '%Y:%m:%d %H:%M:%S.%f')
        if sn:
            xmp_info['SeriesNumber'] = sn

        return xmp_info


def get_weibo_pages(containerid: str, start_page: int = 1, fetch_retweeted=None):
    """
    [summary]

    Returns:
        [type]: [description]

    Yields:
        [type]: [description]
    """
    page = start_page
    while True:
        js = get_json(containerid=containerid, page=page)
        mblogs = [w['mblog']
                  for w in js['data']['cards'] if w['card_type'] == 9]
        if not js['ok']:
            assert not mblogs
            logger.warning(
                f"not js['ok'], seems reached end, no wb return for page {page}")
            break

        for weibo_info in mblogs:
            is_retweeted = ('retweeted_status' in weibo_info)
            if (fetch_retweeted is not None) and not (is_retweeted ^ fetch_retweeted):
                continue
            weibo = _parse_weibo(weibo_info)
            yield Weibo(weibo)

        logger.success(f"++++++++ 页面 {page} 获取完毕 ++++++++++\n")
        pause(mode='page')
        page += 1


def get_weibo_by_id(wb_id):
    url = f'https://m.weibo.cn/detail/{wb_id}'
    html = get_url(url).text
    html = html[html.find('"status"'):]
    html = html[:html.rfind('"hotScheme"')]
    html = html[:html.rfind(',')]
    html = f'{{{html}}}'
    weibo_info = json.loads(html, strict=False)['status']
    weibo = _parse_weibo(weibo_info)
    return weibo


def _parse_weibo(weibo_info):
    if 'retweeted_status' not in weibo_info:
        return WeiboParser(weibo_info).wb
    original = weibo_info['retweeted_status']
    if original['pic_num'] > 9 or original['isLongText']:
        original = Weibo.from_weibo_id(int(weibo_info['id']))
    else:
        original = _parse_weibo(original)
    retweet = WeiboParser(weibo_info).wb
    original.update(
        retweet_by=retweet['screen_name'],
        retweet_by_id=retweet['user_id'],
        retweet_id=retweet['id'],
        retweet_bid=retweet['bid'],
        retweet_url=retweet['url'],
        retweet_text=retweet['text']
    )
    return original


class WeiboParser:
    def __init__(self, weibo_info):
        self.info = weibo_info
        self.wb = {}
        self.basic_info()
        self.photos_info()
        self.video_info()
        if text := weibo_info['text'].strip():
            self.selector = etree.HTML(text)
            self.soup = BeautifulSoup(text, 'lxml')
            assert self.selector_info() == self.soup_info()
            self.wb |= self.soup_info()
        self.wb = {k: v for k, v in self.wb.items() if v or v == 0}

    def basic_info(self):
        id_ = self.info['id']
        bid = self.info['bid']
        user = self.info['user']
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

    def soup_info(self):

        at_list, topics_list = [], []

        for a in self.soup.find_all('a'):
            at_sign, user = a.text[0], a.text[1:]
            if at_sign == '@':
                assert a.attrs['href'][3:] == user
                at_list.append(user)

        for topic in self.soup.find_all('span', class_='surl-text'):
            if m := re.match('^#(.*)#$', topic.text):
                topics_list.append(m.group(1))

        location = ''
        if url_icon := self.soup.find('span', class_='url-icon'):
            location_icon = 'timeline_card_small_location_default.png'
            if location_icon in url_icon.find('img').attrs['src']:
                location_span = url_icon.findNext('span')
                assert location_span.attrs['class'] == ['surl-text']
                location = location_span.text
        return {
            'text': self.soup.text,
            'at_users': at_list,
            'topics': topics_list,
            'location': location
        }

    def selector_info(self):
        text = self.selector.xpath('string(.)')
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
        return {
            'text': text,
            'at_users': at_list,
            'topics': topics_list,
            'location': location
        }

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
