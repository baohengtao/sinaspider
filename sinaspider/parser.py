import html
import json
import re
import time
import warnings

import bs4
import pendulum
from bs4 import BeautifulSoup

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError, WeiboNotFoundError
from sinaspider.helper import fetcher, normalize_str


class WeiboParser:
    """用于解析原始微博内容."""

    def __init__(self, weibo_info: dict | int | str):
        if isinstance(weibo_info, (int, str)):
            self.info = self._fetch_info(weibo_info)
            assert self.pic_match
        else:
            self.info = weibo_info
        self.is_pinned = self.info.get('title', {}).get('text') == '置顶'
        if self.info['pic_num'] < len(self.info['pic_ids']):
            console.log(
                f"pic_num < len(pic_ids) for {self.info['id']}",
                style="warning")
        self.weibo = {}

    @property
    def pic_match(self) -> bool:
        return self.info['pic_num'] <= len(self.info['pic_ids'])

    @staticmethod
    def _fetch_info(weibo_id: str | int) -> dict:
        url = f'https://m.weibo.cn/detail/{weibo_id}'
        text = fetcher.get(url).text
        soup = BeautifulSoup(text, 'html.parser')
        if soup.title.text == '微博-出错了':
            raise WeiboNotFoundError(soup.body.get_text(' ', strip=True))
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

        return weibo_info

    def parse(self, online=True):
        if online and not self.pic_match:
            assert self.info['pic_num'] > 9
            self.info = self._fetch_info(self.info['id'])
            assert self.pic_match
        self.basic_info()
        self.photos_info()
        self.video_info()
        self.weibo |= self.text_info_v2()
        self.weibo = {k: v for k, v in self.weibo.items() if v or v == 0}
        if self.is_pinned:
            self.weibo['is_pinned'] = self.is_pinned
        if self.pic_match:
            self.weibo['update_status'] = 'updated'
        return self.weibo

    def basic_info(self):
        user = self.info['user']
        created_at = pendulum.from_format(
            self.info['created_at'], 'ddd MMM DD HH:mm:ss ZZ YYYY')
        assert created_at.is_local()
        if region_name := self.info.get('region_name'):
            region_name = region_name.removeprefix('发布于').strip()
        self.weibo.update(
            user_id=(user_id := user['id']),
            id=(id_ := int(self.info['id'])),
            bid=(bid := self.info.get('bid')),
            username=user.get('remark') or user['screen_name'],
            url=f'https://weibo.com/{user_id}/{bid or id_}',
            url_m=f'https://m.weibo.cn/detail/{id_}',
            created_at=created_at,
            source=self.info['source'].strip(),
            retweeted=self.info.get('retweeted_status', {}).get('bid'),
            region_name=region_name,
        )
        for key in ['reposts_count', 'comments_count', 'attitudes_count']:
            if (v := self.info[key]) == '100万+':
                v = 1000000
            self.weibo[key] = v

    def photos_info(self):
        self.weibo['pic_num'] = self.info['pic_num']
        if self.weibo['pic_num'] == 0:
            return
        photos = {}
        if 'pic_infos' in self.info:
            for i, pic_id in enumerate(self.info['pic_ids'], start=1):
                pic_info = self.info['pic_infos'][pic_id]
                photos[str(i)] = [
                    pic_info['largest']['url'], pic_info.get('video')]
        elif pics := self.info.get('pics'):
            pics = pics.values() if isinstance(pics, dict) else pics
            pics = [p for p in pics if 'pid' in p]
            for i, pic in enumerate(pics, start=1):
                photos[str(i)] = [pic['large']['url'], pic.get('videoSrc')]
        else:
            assert self.weibo['pic_num'] == 1
            page_info = self.info['page_info']
            page_pic = page_info['page_pic']
            url = page_pic if isinstance(
                page_pic, str) else page_pic['url']
            photos['1'] = [url, None]

        assert len(photos) == len(self.info['pic_ids'])
        self.weibo['photos'] = photos

    def video_info(self):
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

    # @staticmethod
    # def text_info(text: str):
    #     if not text.strip():
    #         return {}
    #     at_list, topics_list = [], []
    #     with warnings.catch_warnings(
    #         action='ignore',
    #         category=bs4.MarkupResemblesLocatorWarning
    #     ):
    #         soup = BeautifulSoup(text, 'html.parser')

    #     for a in soup.find_all('a'):
    #         at_sign, user = a.text[0], a.text[1:]
    #         if at_sign == '@':
    #             assert a.attrs['href'][3:] == user
    #             at_list.append(user)

    #     for topic in soup.find_all('span', class_='surl-text'):
    #         if m := re.match('^#(.*)#$', topic.text):
    #             topics_list.append(m.group(1))

    #     location, location_id, location_src = '', '', ''
    #     location_collector = []
    #     for url_icon in soup.find_all('span', class_='url-icon'):
    #         location_icon = 'timeline_card_small_location_default.png'
    #         if location_icon in url_icon.find('img').attrs['src']:
    #             location_span = url_icon.findNext('span')
    #             assert location_span.attrs['class'] == ['surl-text']
    #             location_collector.append(
    #                 [location_span.text, location_span.parent.attrs['href']])
    #     if location_collector:
    #         location, href = location_collector[-1]
    #         pattern1 = r'http://weibo\.com/p/100101(\w+)'
    #         pattern2 = (r'https://m\.weibo\.cn/p/index\?'
    #                     r'containerid=2306570042(\w+)')
    #         if match := (re.search(pattern1, href)
    #                      or re.search(pattern2, href)):
    #             location_id = match.group(1)
    #         else:
    #             console.log(
    #                 f"cannot parse {location}'s id: {href}", style='error')
    #             location_src = href

    #     return {
    #         # 'text': soup.get_text(' ', strip=True),
    #         'at_users': at_list,
    #         'topics': topics_list,
    #         'location': location,
    #         'location_id': location_id,
    #         'location_src': location_src
    #     }

    def text_info_v2(self):
        hypertext = self.info['text'].strip()
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
                    location_collector.append(
                        [surl_text.text, child.attrs['href']])
                    child.decompose()
                elif _icn_video in url_icon.img.attrs['src']:
                    child.decompose()
        location, location_id, location_src = '', '', ''
        if location_collector:
            assert len(location_collector) <= 2
            location, href = location_collector[-1]
            pattern1 = r'http://weibo\.com/p/100101(\w+)'
            pattern2 = (r'https://m\.weibo\.cn/p/index\?containerid='
                        r'2306570042(\w+)')
            if match := (re.search(pattern1, href)
                         or re.search(pattern2, href)):
                location_id = match.group(1)
            else:
                console.log(
                    f"cannot parse {location}'s id: {href}", style='error')
                location_src = href
        res = {
            'at_users': at_users,
            'topics': topics,
            'location': location,
            'location_id': location_id,
            'location_src': location_src
        }
        text = soup.get_text(' ', strip=True)
        assert text == text.strip()
        if location:
            text = text.removesuffix('📍')
            assert not text.endswith('📍')
            text += f' 📍{location}'
        res['text'] = text.strip()
        # for k, v in self.text_info(hypertext).items():
        #     assert res[k] == v
        return res


class UserParser:
    def __init__(self, user_id) -> None:
        self.id = user_id
        self._user = None

    def parse(self) -> dict:
        while True:
            try:
                return self._parse()
            except (AssertionError, KeyError):
                console.log(
                    f'AssertionError, retrying parse user {self.id}',
                    style='error')
                time.sleep(60)

    def _parse(self) -> dict:
        if self._user is not None:
            return self._user.copy()
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

        if not (descrip := user_info['description']):
            user_info.pop('description')
        else:
            user_info['description'] = html.unescape(descrip)

        assert 'followed_by' not in user_info
        if followed_by := self.followed_by():
            user_info['followed_by'] = followed_by
        self._user = self._normalize(user_info)

        return self._user.copy()

    @staticmethod
    def _normalize(user_info: dict) -> dict:
        user = {k: normalize_str(v) for k, v in user_info.items()}
        assert 'homepage' not in user
        assert 'username' not in user
        assert 'age' not in user
        if remark := user.pop('remark', ''):
            user['username'] = remark
        user['homepage'] = f'https://weibo.com/u/{user["id"]}'
        console.log(f"{remark or user['screen_name']} 信息已从网络获取.")
        for v in user.values():
            assert v or v == 0
        return user

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
        """获取来自cn的信息."""
        r = fetcher.get(f'https://weibo.cn/{self.id}/info')

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
                lines = "".join('\n' if child.name == 'br' else child.text
                                for child in c.children).strip()
                for line in lines.split('\n'):
                    key, value = re.split('[:：]', line, maxsplit=1)
                    info[key] = value
            elif tip.text in ['学习经历', '工作经历']:
                info[tip.text] = (c.text
                                  .strip('·').replace('\xa0', ' ')
                                  .strip().split('·'))
            else:
                assert tip.text == '其他信息'
        assert info.get('认证') == info.pop('认证信息', None)
        return info

    def _fetch_user_card(self) -> dict:
        """获取来自m.weibo.com的信息."""
        url = ('https://m.weibo.cn/api/container/'
               f'getIndex?containerid=230283{self.id}_-_INFO')
        js = fetcher.get(url).json()
        user_card = js['data']['cards']
        user_card = sum([c['card_group'] for c in user_card], [])
        user_card = {card['item_name']: card['item_content']
                     for card in user_card if 'item_name' in card}
        user_card['备注'] = user_card.pop('Tap to set alias', '')

        if ip := user_card.pop('IP属地', ""):
            user_card['IP'] = ip.replace("（IP属地以运营商信息为准，如有问题可咨询客服）", "")
        return user_card

    def get_user_info(self) -> dict:
        """获取主信息."""
        url = ('https://m.weibo.cn/api/container/getIndex?'
               f'containerid=100505{self.id}')
        while not (js := fetcher.get(url).json())['ok']:
            console.log(
                f'not js[ok] for {url}, sleeping 60 secs...', style='warning')
            time.sleep(60)
        user_info = js['data']['userInfo']
        keys = ['cover_image_phone', 'profile_image_url',
                'profile_url', 'toolbar_menus', 'badge']
        for key in keys:
            user_info.pop(key, None)
        assert user_info['followers_count'] == user_info.pop(
            'followers_count_str')
        assert user_info.pop('close_blue_v') is False
        return user_info

    def get_user_info_v2(self) -> dict:
        url = ('https://api.weibo.cn/2/profile?&c=weicoabroad'
               f'&from=129C893010&s=dddddddd&user_domain={self.id}')
        js = fetcher.get(url).json()
        user_info = js['userInfo']
        to_pop = [
            'status', 'badge', 'avatar_extend_info', 'extend', 'dialog',
            'profile_image_url', 'cover_image_phone', 'lang',
            'follower_number_text', 'covers'
        ]
        for key in to_pop:
            user_info.pop(key)
        return {k: v for k, v in user_info.items() if v != '' and v != 0}

    def followed_by(self) -> list[int] | None:
        """
        fetch users' id  who follow this user and also followed by me.

        Returns:
            list[int] | None: list of users' id
        """
        url = ("https://api.weibo.cn/2/cardlist?"
               "from=10CB193010&c=iphone&s=BF3838D9"
               f"&containerid=231051_-_myfollow_followprofile_-_{self.id}")
        r = fetcher.get(url)
        if not (cards := r.json()['cards']):
            return
        cards = cards[0]['card_group'][1:]
        if len(cards) == 1 and (pics := cards[0].get('pics')):
            uids = [pic['author']['id'] for pic in pics]
        else:
            uids = [card['user']['id'] for card in cards]
        return uids
