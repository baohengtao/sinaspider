import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Union, Generator

import pendulum
from bs4 import BeautifulSoup
from lxml import etree

from sinaspider.helper import logger, get_url, get_json, pause


class Weibo(OrderedDict):
    from sinaspider.database import weibo_table as table
    from sinaspider.helper import config as _config
    if _config().as_bool('write_xmp'):
        from exiftool import ExifTool
        et = ExifTool()
        et.start()
    else:
        et = None

    def __init__(self, *args, **kwargs):
        """可使用 Weibo(weibo_id)获得微博信息"""
        if kwargs or args[1:] or not isinstance(args[0], int):
            super().__init__(*args, **kwargs)
        else:
            super().__init__(self._from_weibo_id(args[0]))

    @classmethod
    def _from_weibo_id(cls, wb_id):
        """从数据库获取微博信息, 若不在其中, 则尝试从网络获取, 并将获取结果存入数据库"""
        assert isinstance(wb_id, int), wb_id
        docu = cls.table.find_one(id=wb_id) or {}
        return cls(docu) or get_weibo_by_id(wb_id)

    def update_table(self):
        self.table.upsert(self, ['id'])

    def __str__(self):
        text = ''
        keys = [
            'screen_name', 'id', 'text', 'location',
            'created_at', 'at_users', 'url'
        ]
        for k in keys:
            if v := self.get(k):
                text += f'{k}: {v}\n'
        return text

    def save_media(self, download_dir: Union[str, Path]) -> list:
        """
        保存微博图片 / 视频到指定目录. 若为转发微博, 则保持到`retweet`子文件夹中

        Args:
            download_dir (Union[str|Path]): 文件保存目录
        Returns:
            list: 返回下载列表
        """
        download_dir = Path(download_dir)
        if original_id := self.get('original_id'):
            download_dir /= 'retweet'
            return self._from_weibo_id(original_id).save_media(download_dir)
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
                    'xmp_info': self.to_xmp(sn, with_prefix=True)})
        # add video urls to list
        if url := self.get('video_url'):
            assert ';' not in url
            filepath = f'{prefix}.mp4'
            download_list.append({
                'url': url,
                'filepath': Path(filepath),
                'xmp_info': self.to_xmp(with_prefix=True)})

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
            if self.et: self.et.set_tags(dl['xmp_info'], str(filepath))

        return download_list

    def to_xmp(self, sn=0, with_prefix=False) -> dict:
        """
        生产图片元数据

        Args:
            sn (, optional): 图片序列 SeriesNumber 信息 (即图片的次序)
            with_prefix:  是否添加'XMP:'前缀

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
        if not with_prefix:
            return xmp_info
        else:
            return {'XMP:' + k: v for k, v in xmp_info.items()}


def get_weibo_pages(containerid: str,
                    retweet: bool = True,
                    start_page: int = 1,
                    end_page=None,
                    since=None,
                    download_dir=None
                    ) -> Generator[Weibo, None, None]:
    """
    爬取某一 containerid 类型的所有微博

    Args:
        containerid(str): 
            - 获取用户页面的微博: f"107603{user_id}"
            - 获取收藏页面的微博: 230259
        retweet (bool): 是否爬取转发微博
        start_page(int): 指定从哪一页开始爬取, 默认第一页.
        end_page: 最大获取页数, 默认所有页面
        since: 从哪天开始爬取, 默认所有时间
        download_dir: 下载目录, 若为空, 则不下载


    Yields:
        Generator[Weibo]: 生成微博实例
    """
    page = max(start_page, 1)
    while True:
        js = get_json(containerid=containerid, page=page)
        if not js['ok']:
            if js['msg'] == '请求过于频繁，歇歇吧':
                logger.critical('be banned')
                return js
            else:
                logger.warning(
                    f"not js['ok'], seems reached end, no wb return for page {page}")
                break

        mblogs = [w['mblog']
                  for w in js['data']['cards'] if w['card_type'] == 9]

        for weibo_info in mblogs:
            weibo = None
            if 'retweeted_status' in weibo_info:
                if retweet:
                    # 若原微博已删除, 返回None
                    # 否则分别将原微博和转发微博分别解析并写入数据库
                    weibo = _parse_weibo(weibo_info)
            elif weibo_info['pic_num'] > 9 or weibo_info['isLongText']:
                # 若为原创长微博, 则爬取原链接
                weibo = get_weibo_by_id(weibo_info['id'])
            else:
                weibo = _parse_weibo(weibo_info)
            if not weibo:
                continue
            if weibo['created_at'] < since:
                if weibo['is_pinned']:
                    logger.warning(f"发现置顶微博, 跳过...")
                    continue
                else:
                    logger.info(
                        f"时间{weibo['created_at']} 在 {since:%y-%m-%d}之前, 获取完毕")
                    end_page = page
                    break
                    
            if download_dir:
                weibo.save_media(download_dir)

        logger.success(f"++++++++ 页面 {page} 获取完毕 ++++++++++\n")
        page += 1
        if end_page  and page > end_page:
            break
        pause(mode='page')


def get_weibo_by_id(wb_id: Union[int, str]) -> Union[Weibo, None]:
    """
    爬取指定id的微博, 若原微博已删除, 返回None

    Args:
        wb_id (Union[int, str]): 微博id

    Returns:
        Weibo instance if exists, else None

    """
    url = f'https://m.weibo.cn/detail/{wb_id}'
    html = get_url(url).text
    html = html[html.find('"status"'):]
    html = html[:html.rfind('"hotScheme"')]
    html = html[:html.rfind(',')]
    if not html:
        return
    html = f'{{{html}}}'
    weibo_info = json.loads(html, strict=False)['status']
    return _parse_weibo(weibo_info)


def _parse_weibo(weibo_info: dict) -> Union[Weibo, None]:
    """
    对从网页爬取到的微博进行解析.
    若为转发微博:
        若原微博已删除, 返回 None;
        若原微博为长微博, 则爬取原微博并解析
    若为原创微博, 则直接解析 
    

    Args:
        weibo_info (dict): 原始微博信息

    Returns:
        解析后的微博信息. 若为转发的原微博已删除, 返回None
    """

    if 'retweeted_status' not in weibo_info:
        return _WeiboParser(weibo_info).weibo
    original = weibo_info['retweeted_status']
    delete_text = [
        "该账号因被投诉违反法律法规和《微博社区公约》的相关规定，现已无法查看。查看帮助",
        "抱歉，作者已设置仅展示半年内微博，此微博已不可见。",
        "抱歉，此微博已被作者删除。查看帮助"
    ]
    for d in delete_text:
        if d in original['text']:
            return

    if original['pic_num'] > 9 or original['isLongText']:
        original = Weibo(int(original['id']))
    else:
        original = _parse_weibo(original)
    retweet = _WeiboParser(weibo_info).weibo
    retweet.update(
        original_id=original['id'],
        original_bid=original['bid'],
        original_uid=original['user_id'],
        original_text=original['text']
    )
    retweet.update_table()
    return retweet


class _WeiboParser:
    """用于解析原始微博内容"""

    def __init__(self, weibo_info):
        self.info = weibo_info
        self.wb = OrderedDict()
        self.parse_info()

    def parse_info(self):
        self.basic_info()
        self.photos_info()
        self.video_info()
        text = self.info['text'].strip()
        self.wb |= text_info(text)
        self.wb = {k: v for k, v in self.wb.items() if v or v == 0}

    @property
    def weibo(self) -> Weibo:
        """
        return Weibo object and also update weibo table
        """
        keys = ['id', 'bid', 'user_id', 'screen_name', 'created_at', 'text']
        wb, ordered_info = self.wb.copy(), OrderedDict()
        for key in keys:
            if key in wb:
                ordered_info[key] = wb.pop(key)
        ordered_info |= wb
        weibo = Weibo(ordered_info)
        weibo.update_table()
        return weibo

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
            'inch_4_mp4_hd', 'inch_5_mp4_hd', 'inch_5_5_mp4_hd', 'duration'
        ]
        if not set(media_info).issubset(keys):
            logger.info(media_info)
            logger.info(str(set(media_info) - set(keys)))
            assert False
        urls = [v for k in keys if (v := media_info.get(k))]
        if not urls:
            logger.warning(f'no video info:==>{page_info}')
        else:
            self.wb['video_url'] = urls[0]


def text_info(text):
    if not text.strip():
        return {}
    at_list, topics_list = [], []
    soup = BeautifulSoup(text, 'lxml')

    for a in soup.find_all('a'):
        at_sign, user = a.text[0], a.text[1:]
        if at_sign == '@':
            assert a.attrs['href'][3:] == user
            at_list.append(user)

    for topic in soup.find_all('span', class_='surl-text'):
        if m := re.match('^#(.*)#$', topic.text):
            topics_list.append(m.group(1))

    location = ''

    for url_icon in soup.find_all('span', class_='url-icon'):
        location_icon = 'timeline_card_small_location_default.png'
        if location_icon in url_icon.find('img').attrs['src']:
            location_span = url_icon.findNext('span')
            assert location_span.attrs['class'] == ['surl-text']
            location = location_span.text
    res = {
        'text': soup.text,
        'at_users': at_list,
        'topics': topics_list,
        'location': location
    }
    for k, v in res.items():
        if k != 'text':
            sv = _selector_info(text)[k]
            if not sv == v:
                logger.info(sv)
                logger.info(v)
                logger.info(res)
                logger.info(soup)
                assert False
    return res


def _selector_info(text):
    selector = etree.HTML(text)
    text = selector.xpath('string(.)')
    at_list, topics_list = [], []

    for a in selector.xpath('//a'):
        at_user = a.xpath('string(.)')
        if at_user[0] != '@':
            continue
        at_user = at_user[1:]
        assert a.xpath('@href')[0][3:] == at_user
        at_list.append(at_user)

    for topic in selector.xpath("//span[@class='surl-text']"):
        t = topic.xpath('string(.)')
        if m := re.match('^#(.*)#$', t):
            topics_list.append(m.group(1))

    location = ''
    location_icon = 'timeline_card_small_location_default.png'
    span_list = selector.xpath('//span')
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
