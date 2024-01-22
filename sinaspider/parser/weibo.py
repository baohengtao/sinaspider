import re
import warnings

import bs4
import pendulum
from bs4 import BeautifulSoup

from sinaspider import console
from sinaspider.helper import encode_wb_id, parse_loc_src

from .helper import WeiboHist, parse_photos_info


class WeiboParser:
    """用于解析原始微博内容."""

    def __init__(self, weibo_info: dict, hist_mblogs=None):
        self.info = weibo_info
        self.hist_mblogs = hist_mblogs
        if (pic_num := self.info['pic_num']) < len(self.info['pic_ids']):
            console.log(
                f"pic_num < len(pic_ids) for {self.info['id']}",
                style="warning")
        else:
            assert pic_num == len(self.info['pic_ids'])

    def parse(self):
        weibo = self.basic_info()
        if video := self.video_info():
            weibo |= video
        weibo['photos'] = parse_photos_info(self.info)
        weibo |= self.text_info(self.info['text'])
        if self.hist_mblogs:
            weibo = WeiboHist(weibo, self.hist_mblogs).parse()
        weibo = {k: v for k, v in weibo.items() if v not in ['', [], None]}
        weibo['has_media'] = bool(weibo.get('video_url') or weibo.get(
            'photos') or weibo.get('photos_edited'))

        if loc := weibo.get('location'):
            text = weibo['text'].removesuffix('📍')
            assert not text.endswith('📍')
            text += f' 📍{loc}'
            weibo['text'] = text.strip()

        self.weibo = weibo
        return weibo.copy()

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
            mblog_from=self.info.get('mblog_from'),
            pic_num=self.info['pic_num'],
            edit_count=self.info.get('edit_count', 0),
            update_status='updated',

        )
        for key in ['reposts_count', 'comments_count', 'attitudes_count']:
            if (v := self.info[key]) == '100万+':
                v = 1000000
            weibo[key] = v
        return weibo

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
