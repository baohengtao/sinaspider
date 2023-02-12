import json
import re
import time
from typing import Self
import warnings

import pendulum
import bs4
from bs4 import BeautifulSoup
from sinaspider import console
from sinaspider.helper import get_url, pause, weibo_api_url, normalize_str
from sinaspider.exceptions import WeiboNotFoundError, UserNotFoundError


def get_weibo_by_id(wb_id) -> dict:
    return WeiboParser.from_id(wb_id).weibo


def parse_weibo(weibo_info: dict, offline=False) -> dict:
    """
    对从网页爬取到的微博进行解析.
    Args:
        weibo_info (dict): 原始微博信息
    Returns:
        解析后的微博信息.
    """
    parser = WeiboParser(weibo_info, offline=offline)
    return parser.weibo


class WeiboParser:
    """用于解析原始微博内容"""

    def __init__(self, weibo_info: dict, offline=False):
        if weibo_info['pic_num'] > 9 and not offline:
            weibo_info = self._fetch_info(weibo_info['id'])
        self.info = weibo_info
        self.weibo = {}
        self.parse_card()
        if not offline:
            pic_num = len(self.weibo.get('photos', {}))
            assert pic_num == self.weibo['pic_num']

    @classmethod
    def from_id(cls, id: str | int) -> Self:
        weibo_info = cls._fetch_info(id)
        return cls(weibo_info)

    @staticmethod
    def _fetch_info(weibo_id: str | int) -> dict:
        url = f'https://m.weibo.cn/detail/{weibo_id}'
        text = get_url(url).text
        soup = BeautifulSoup(text, 'html.parser')
        if soup.title.text == '微博-出错了':
            raise WeiboNotFoundError(soup.body.get_text(' ', strip=True))
        rec = re.compile(
            r'.*var \$render_data = \[(.*)]\[0] \|\| \{};', re.DOTALL)
        html = rec.match(text).groups(1)[0]
        weibo_info = json.loads(html, strict=False)['status']
        console.log(f"{weibo_id} fetched in online.")
        pause(mode='page')
        return weibo_info

    def parse_card(self):
        self.basic_info()
        self.photos_info_v2()
        self.video_info_v2()
        self.weibo |= self.text_info(self.info['text'])
        self.weibo = {k: v for k, v in self.weibo.items() if v or v == 0}

    def basic_info(self):
        title = self.info.get('title', {}).get('text', '')
        is_pinned = title == '置顶'
        is_comment = '评论过的微博' in title
        user = self.info['user']
        created_at = pendulum.from_format(
            self.info['created_at'], 'ddd MMM DD HH:mm:ss ZZ YYYY')
        assert created_at.is_local()
        self.weibo.update(
            user_id=(user_id := user['id']),
            id=(id := int(self.info['id'])),
            bid=(bid := self.info.get('bid')),
            username=user['screen_name'],
            gender=user['gender'],
            followers_count=user['followers_count'],
            url=f'https://weibo.com/{user_id}/{bid or id}',
            url_m=f'https://m.weibo.cn/detail/{id}',
            created_at=created_at,
            source=self.info['source'],
            is_pinned=is_pinned,
            is_comment=is_comment,
            retweeted=self.info.get('retweeted_status', {}).get('bid'),
        )
        for key in ['reposts_count', 'comments_count', 'attitudes_count']:
            if (v := self.info[key]) == '100万+':
                v = 1000000
            self.weibo[key] = v

    def photos_info_v2(self):
        self.weibo['pic_num'] = self.info['pic_num']
        if self.weibo['pic_num'] == 0:
            return
        photos = {}
        if 'pic_infos' in self.info:
            for i, pic_id in enumerate(self.info['pic_ids'], start=1):
                pic_info = self.info['pic_infos'][pic_id]
                photos[i] = [
                    pic_info['largest']['url'], pic_info.get('video')]
        elif 'pics' in self.info:
            for i, pic in enumerate(self.info['pics'], start=1):
                photos[i] = [pic['large']['url'], pic.get('videoSrc')]
        else:
            assert self.weibo['pic_num'] == 1
            page_info = self.info['page_info']
            page_pic = page_info['page_pic']
            url = page_pic if isinstance(
                page_pic, str) else page_pic['url']
            photos[1] = [url, None]

            # assert 'article' in [
            #     page_info['object_type'], page_info['type']]
            # console.log(f"Article found for {self.wb['url_m']}, "
            #             "skiping parse image url...",
            #             style='error')
            # self.wb['pic_num'] = 0

        self.weibo['photos'] = photos

    def photos_info(self):
        pics = self.info.get('pics', [])
        if isinstance(pics, dict):
            pics = [p['large']['url']
                    for p in pics.values() if 'large' in p]
        else:
            pics = [p['large']['url'] for p in pics]
        if not pics and (ids := self.info.get('pic_ids')):
            pics = [f'https://wx{i % 3 + 1}.sinaimg.cn/large/{id}'
                    for i, id in enumerate(ids)]
        # pics = [p['large']['url'] for p in pics]
        live_photo = {}
        live_photo_prefix = (
            'https://video.weibo.com/media/play?'
            'livephoto=//us.sinaimg.cn/')
        if pic_video := self.info.get('pic_video'):
            live_photo = {}
            for p in pic_video.split(','):
                sn, path = p.split(':')
                live_photo[int(sn)] = f'{live_photo_prefix}{path}.mov'
            assert max(live_photo) < len(pics)
        self.weibo['photos'] = {str(i + 1): [pic, live_photo.get(i)]
                                for i, pic in enumerate(pics)}

    def video_info_v2(self):
        page_info = self.info.get('page_info', {})
        if not page_info.get('type') == "video":
            return
        keys = ['mp4_1080p_mp4', 'mp4_720p_mp4',
                'mp4_hd_mp4', 'mp4_ld_mp4']
        for key in keys:
            if url := page_info['urls'].get(key):
                self.weibo['video_url'] = url
                break
        else:
            console.log(f'no video info:==>{page_info}', style='error')
            raise ValueError('no video info')

        self.weibo['video_duration'] = page_info['media_info']['duration']

    def video_info(self):
        page_info = self.info.get('page_info', {})
        if not page_info.get('type') == "video":
            return
        media_info = page_info['urls'] or page_info['media_info']
        keys = [
            'mp4_1080p_mp4', 'mp4_720p', 'mp4_720p_mp4', 'mp4_hd_mp4',
            'mp4_hd', 'mp4_hd_url', 'hevc_mp4_hd', 'mp4_ld_mp4', 'mp4_ld',
            'hevc_mp4_ld', 'stream_url_hd', 'stream_url',
            'inch_4_mp4_hd', 'inch_5_mp4_hd', 'inch_5_5_mp4_hd', 'duration'
        ]
        if not set(media_info).issubset(keys):
            console.log(media_info)
            console.log(str(set(media_info) - set(keys)), style='error')
            # assert False
        urls = [v for k in keys if (v := media_info.get(k))]
        if not urls:
            console.log(f'no video info:==>{page_info}', style='warning')
        else:
            self.weibo['video_url'] = urls[0]
            if duration := float(media_info.get('duration', 0)):
                self.weibo['video_duration'] = duration

    @staticmethod
    def text_info(text):
        if not text.strip():
            return {}
        at_list, topics_list = [], []
        with warnings.catch_warnings(
            action='ignore',
            category=bs4.MarkupResemblesLocatorWarning
        ):
            soup = BeautifulSoup(text, 'html.parser')

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
        return {
            'text': soup.get_text(' ', strip=True),
            'at_users': at_list,
            'topics': topics_list,
            'location': location
        }


class UserParser:
    def __init__(self, user_id) -> None:
        self.id = user_id
        self._user = None

    @property
    def user(self) -> dict:
        if self._user is not None:
            return self._user
        user_cn = self.get_user_cn()
        user_info = self.get_user_info()

        assert user_cn.pop('昵称') == user_info['screen_name']
        assert user_cn.pop('备注') == user_info.get('remark', '')
        assert user_cn.pop('简介') == user_info['description']
        assert user_cn.pop('认证', None) == user_info.get('verified_reason')

        cn2en = [('生日', 'birthday'), ('学习经历', 'education'),
                 ('家乡', 'hometown'), ('所在地', 'location')]
        for key_cn, key_en in cn2en:
            assert key_en not in user_info
            if key_cn in user_cn:
                user_info[key_en] = user_cn.pop(key_cn)

        match gender := user_info['gender']:
            case 'f':
                assert user_cn.pop('性别') == '女'
                user_info['gender'] = 'female'
            case 'm':
                assert user_cn.pop('性别') == '男'
                user_info['gender'] = 'male'
            case _:
                raise ValueError(gender)

        for k, v in user_cn.items():
            assert user_info.setdefault(k, v) == v

        if user_info['description'] == '':
            user_info.pop('description')

        self._user = user_info

        return self._user

    def get_user_cn(self) -> dict:
        user_cn = self._fetch_user_cn()
        user_card = self._fetch_user_card()
        assert user_card['所在地'] == user_cn.pop('地区')
        birthday_cn = user_cn.pop('生日', '')
        birthday_card = user_card.pop('生日', '')
        if birthday_cn not in ['0001-00-00', '01-01']:
            assert birthday_cn in birthday_card
        if match := re.search(r'(\d{4}-\d{2}-\d{2})', birthday_card):
            user_cn['生日'] = match.group(1)

        edu_str = " ".join(user_cn.get('学习经历') or [])
        for key in ['大学', '海外', '高中', '初中', '中专技校', '小学']:
            assert user_card.pop(key, '') in edu_str
        for k, v in user_card.items():
            assert user_cn.setdefault(k, v) == v
        if user_cn['简介'] == '暂无简介':
            user_cn['简介'] = ''
        return user_cn

    def _fetch_user_cn(self) -> dict:
        """获取来自cn的信息"""
        r = get_url(f'https://weibo.cn/{self.id}/info')

        with warnings.catch_warnings(
            action='ignore',
            category=bs4.XMLParsedAsHTMLWarning
        ):
            soup = BeautifulSoup(r.text, 'lxml')
        if div := soup.body.find('div', class_='ps'):
            if div.text == 'User does not exists!':
                raise UserNotFoundError(f"{self.id}: {div.text}")

        info = {}
        for tip in soup.body.children:
            assert tip.name == 'div'
            if tip['class'] != ['tip']:
                continue
            else:
                c = tip.next_sibling
                assert c.name == 'div'
                assert c['class'] == ['c']

            if tip.text == '基本信息':
                for line in c.get_text(separator='\n').split('\n'):
                    key, value = re.split('[:：]', line, maxsplit=1)
                    info[key] = value
            elif tip.text in ['学习经历', '工作经历']:
                info[tip.text] = c.text.strip(
                    '·').replace('\xa0', ' ').split('·')
            else:
                assert tip.text == '其他信息'
        assert info.get('认证') == info.pop('认证信息', None)
        return info

    def _fetch_user_card(self) -> dict:
        """获取来自m.weibo.com的信息"""
        url = weibo_api_url.copy()
        url.args = {'containerid': f"230283{self.id}_-_INFO"}
        js = get_url(url).json()
        user_card = js['data']['cards']
        user_card = sum([c['card_group'] for c in user_card], [])
        user_card = {card['item_name']: card['item_content']
                     for card in user_card if 'item_name' in card}
        user_card['备注'] = user_card.pop('Tap to set alias', '')

        if ip := user_card.pop('IP属地', ""):
            user_card['IP'] = ip.replace("（IP属地以运营商信息为准，如有问题可咨询客服）", "")
        return user_card

    def get_user_info(self) -> dict:
        """获取主信息"""
        url = weibo_api_url.copy()
        url.args = {'containerid': f"100505{self.id}"}
        while not (js := get_url(url).json())['ok']:
            console.log(
                f'not js[ok] for {url}, sleeping 60 secs...', style='error')
            time.sleep(60)
        user_info = js['data']['userInfo']
        keys = ['cover_image_phone', 'profile_image_url',
                'profile_url', 'toolbar_menus']
        for key in keys:
            user_info.pop(key)
        assert user_info['followers_count'] == user_info.pop(
            'followers_count_str')
        return user_info


def get_user_by_id(uid: int):
    user = UserParser(uid).user
    user = {k: normalize_str(v) for k, v in user.items()}
    assert 'homepage' not in user
    assert 'username' not in user
    assert 'age' not in user
    if remark := user.pop('remark', ''):
        user['username'] = remark
    if birthday := user.get('birthday'):
        user['age'] = pendulum.parse(birthday).diff().years
    user['homepage'] = f'https://weibo.com/u/{user["id"]}'
    console.log(f"{remark or user['screen_name']} 信息已从网络获取.")
    for v in user.values():
        assert v or v == 0
    pause(mode='page')
    return user
