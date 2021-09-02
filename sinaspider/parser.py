import json
import re
from collections import OrderedDict
from typing import Union

import pendulum
from bs4 import BeautifulSoup
from lxml import etree

from sinaspider.helper import logger, get_url
from sinaspider.weibo import Weibo


def get_weibo_by_id(wb_id):
    weibo_info = _get_weibo_info_by_id(wb_id)
    return parse_weibo(weibo_info)


def parse_weibo(weibo_info: dict) -> Union[Weibo, None]:
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
    if weibo_info['pic_num'] > 9 or weibo_info['isLongText']:
        weibo_info = _get_weibo_info_by_id(weibo_info['id'])
        assert 'retweeted_status' not in weibo_info
    if original := weibo_info.get('retweeted_status'):
        delete_text = [
            "该账号因被投诉违反法律法规和《微博社区公约》的相关规定，现已无法查看。查看帮助",
            "抱歉，作者已设置仅展示半年内微博，此微博已不可见。",
            "抱歉，此微博已被作者删除。查看帮助"
        ]
        if any(d in original['text'] for d in delete_text):
            return
        if original['pic_num'] > 9 or original['isLongText']:
            original = _get_weibo_info_by_id(original['id'])
        parse_weibo_card(original)

    return parse_weibo_card(weibo_info)


def _get_weibo_info_by_id(wb_id: Union[int, str]) -> Union[Weibo, None]:
    """
    爬取指定id的微博, 若原微博已删除, 返回None

    Args:
        wb_id (Union[int, str]): 微博id

    Returns:
        Weibo instance if exists, else None

    """
    url = f'https://m.weibo.cn/detail/{wb_id}'
    response = get_url(url, expire_after=-1)
    if response.from_cache:
        logger.info(f'fetching {wb_id} from cache')
    html = response.text
    html = html[html.find('"status"'):]
    html = html[:html.rfind('"hotScheme"')]
    html = html[:html.rfind(',')]
    if not html:
        return
    html = f'{{{html}}}'
    weibo_info = json.loads(html, strict=False)['status']
    return weibo_info


def parse_weibo_card(weibo_card):
    class _WeiboCardParser:
        """用于解析原始微博内容"""

        def __init__(self):
            self.card = weibo_card
            self.wb = OrderedDict()
            self.parse_card()

        def parse_card(self):
            self.basic_info()
            self.photos_info()
            self.video_info()
            self.wb |= text_info(self.card['text'])
            self.retweet_info()
            self.wb = {k: v for k, v in self.wb.items() if v or v == 0}

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

        def retweet_info(self):
            if original := self.card.get('retweeted_status'):
                self.wb.update(
                    original_id=original['id'],
                    original_bid=original['bid'],
                    original_uid=original['user']['id'],
                    original_text=text_info(original['text'])['text']
                )

        def basic_info(self):
            id_ = self.card['id']
            bid = self.card['bid']
            user = self.card['user']
            user_id = user['id']
            screen_name = user.get('remark') or user['screen_name']
            created_at = pendulum.parse(self.card['created_at'], strict=False)
            assert created_at.is_local()
            self.wb.update(
                user_id=user_id,
                screen_name=screen_name,
                id=int(self.card['id']),
                bid=bid,
                url=f'https://weibo.com/{user_id}/{bid}',
                url_m=f'https://m.weibo.cn/detail/{id_}',
                created_at=created_at,
                source=self.card['source'],
                is_pinned=(self.card.get('title', {}).get('text') == '置顶')
            )
            for key in ['reposts_count', 'comments_count', 'attitudes_count']:
                self.wb[key]=self.card[key]

        def photos_info(self):
            pics = self.card.get('pics', [])
            pics = [p['large']['url'] for p in pics]
            live_photo = {}
            live_photo_prefix = 'https://video.weibo.com/media/play?livephoto=//us.sinaimg.cn/'
            if pic_video := self.card.get('pic_video'):
                live_photo = pic_video.split(',')
                live_photo = [p.split(':') for p in live_photo]
                live_photo = {
                    int(sn): f'{live_photo_prefix}{path}.mov' for sn, path in live_photo}
                assert max(live_photo) < len(pics)
            self.wb['photos'] = {str(i + 1): [pic, live_photo.get(i)]
                                 for i, pic in enumerate(pics)}

        def video_info(self):
            page_info = self.card.get('page_info', {})
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

    return _WeiboCardParser().weibo()
