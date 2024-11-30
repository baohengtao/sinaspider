import asyncio
import html
import re
import warnings

import bs4
from bs4 import BeautifulSoup

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.helper import fetcher, normalize_str


class UserParser:
    def __init__(self, user_id) -> None:
        self.id = user_id
        self._user = None

    async def parse(self) -> dict:
        while True:
            try:
                return await self._parse()
            except (AssertionError, KeyError):
                console.log(
                    f'AssertionError, retrying parse user {self.id}',
                    style='error')
                await asyncio.sleep(60)

    async def _parse(self) -> dict:
        if self._user is not None:
            return self._user.copy()
        user_cn = await self.get_user_cn()
        user_info = await self.get_user_info()

        assert user_cn.pop('昵称') == user_info['screen_name']
        if x := user_cn.pop('备注', ''):
            assert x == user_info.get('remark', '')
        assert user_cn.pop('简介', '') == user_info.get('description', '')
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

        if not (descrip := user_info.get('description')):
            assert 'description' not in user_info
        else:
            user_info['description'] = html.unescape(descrip)

        assert 'followed_by' not in user_info
        if followed_by := await self.followed_by():
            user_info['followed_by'] = followed_by
        self._user = self._normalize(user_info)

        return self._user.copy()

    @staticmethod
    def _normalize(user_info: dict) -> dict:
        user = {k: normalize_str(v) for k, v in user_info.items()}
        assert user.pop('special_follow') is False
        assert 'homepage' not in user
        assert 'username' not in user
        assert 'age' not in user
        assert 'nickname' not in user
        user['nickname'] = user.pop('screen_name')
        if remark := user.pop('remark', ''):
            user['username'] = remark
        user['homepage'] = f'https://weibo.com/u/{user["id"]}'
        console.log(f"{remark or user['nickname']} 信息已从网络获取.")
        for v in user.values():
            assert v or v == 0
        return user

    async def get_user_cn(self) -> dict:
        user_cn = await self._fetch_user_cn()
        user_card = await self._fetch_user_card()
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
            v = v.strip()
            assert user_cn.setdefault(k, v) == v
        if user_cn['简介'] == '暂无简介':
            user_cn['简介'] = ''
        user_cn = {k: v for k, v in user_cn.items() if v != ''}
        return user_cn

    async def _fetch_user_cn(self) -> dict:
        """获取来自cn的信息."""
        r = await fetcher.get(f'https://weibo.cn/{self.id}/info', art_login=True)

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
                if text := (c.text
                            .strip('·').replace('\xa0', ' ')
                            .strip()):
                    info[tip.text] = text.split('·')
            else:
                assert tip.text == '其他信息'
        assert info.get('认证') == info.pop('认证信息', None)
        return info

    async def _fetch_user_card(self) -> dict:
        """获取来自m.weibo.com的信息."""
        url = ('https://m.weibo.cn/api/container/'
               f'getIndex?containerid=230283{self.id}_-_INFO')
        js = await fetcher.get_json(url, art_login=True)
        user_card = js['data']['cards']
        user_card = sum([c['card_group'] for c in user_card], [])
        user_card = {card['item_name']: card['item_content']
                     for card in user_card if 'item_name' in card}
        user_card['备注'] = user_card.pop('Tap to set alias', '')

        if ip := user_card.pop('IP属地', ""):
            user_card['IP'] = ip.replace("（IP属地以运营商信息为准，如有问题可咨询客服）", "")
        return user_card

    async def get_user_info(self) -> dict:
        """获取主信息."""
        url = ('https://m.weibo.cn/api/container/getIndex?'
               f'containerid=100505{self.id}')
        while not (js := await fetcher.get_json(url, art_login=True))['ok']:
            console.log(
                f'not js[ok] for {url}, sleeping 60 secs...', style='warning')
            await asyncio.sleep(60)
        user_info = js['data']['userInfo']
        keys = ['cover_image_phone', 'profile_image_url',
                'profile_url', 'toolbar_menus', 'badge']
        for key in keys:
            user_info.pop(key, None)
        assert user_info['followers_count'] == user_info.pop(
            'followers_count_str')
        assert user_info.pop('close_blue_v') is False
        for k, v in user_info.copy().items():
            if isinstance(v, str):
                if not (v := v.strip()):
                    user_info.pop(k)
                else:
                    user_info[k] = v
        return user_info

    async def followed_by(self) -> list[int] | None:
        """
        fetch users' id  who follow this user and also followed by me.

        Returns:
            list[int] | None: list of users' id
        """
        url = ("https://api.weibo.cn/2/cardlist?"
               "from=10DA093010&c=iphone&s=ba74941a"
               f"&containerid=231051_-_myfollow_followprofile_list_-_{self.id}")
        js = await fetcher.get_json(url, art_login=True)
        if not (cards := js['cards']):
            return
        cards = cards[0]['card_group']
        uids = [card['user']['id'] for card in cards]
        return uids
