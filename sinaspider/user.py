import re
from time import sleep

import pendulum
import requests
from unipath import Path

from sinaspider.config import headers
from sinaspider.helper import get_json, logger, pause, pg
from sinaspider.weibo import Weibo

USER_TABLE = 'user'
user_table = pg[USER_TABLE]


class User(dict):

    @classmethod
    def _fetch(cls, user_id):
        """
        从网络上获取用户信息
        """
        user_info = get_json(containerid=f"100505{user_id}")
        user_info = user_info['data']['userInfo']
        user_info.pop('toolbar_menus')
        user_cards = get_json(containerid=f"230283{user_id}_-_INFO")
        user_cards = user_cards['data']['cards']
        user_cards = sum([c['card_group'] for c in user_cards], [])
        user_cards = {card['item_name']: card['item_content'] for card in user_cards if 'item_name' in card}
        user_info.update(user_cards)
        user_info['homepage'] = f'https://weibo.com/u/{user_id}'
        user_info = {k: v for k, v in user_info.items() if v or v == 0}
        user = _user_info_fix(user_info)
        user['updated'] = pendulum.now()
        # 获取用户数据
        logger.info(f"{user['screen_name']} 信息已获取.")
        pause(mode='following')
        return cls(user)

    @classmethod
    def from_user_id(cls, user_id, offline=False):
        docu = user_table.find(id=user_id) or {}
        if offline:
            return cls(docu)
        if docu and (updated := docu.get('updated')):
            if pendulum.instance(updated).diff().days < 15:
                return cls(docu)
        user = cls._fetch(user_id)
        user_table.upsert(user, ['id'])
        return cls(user)

    def print(self):
        keys = ['id', 'screen_name', 'gender',
                'birthday', 'location',
                'homepage', 'description',
                'statuses_count', 'followers_count', 'follow_count']

        logger.info('+' * 100)
        for k in keys:
            if v := self.get(k):
                logger.info(f'{k}: {v}')
        logger.info('+' * 100)

    def following(self):
        page = 0
        while True:
            page += 1
            js = get_json(containerid=f'231051_-_followers_-_{self["id"]}', page=page)
            if not js['ok']:
                logger.success(f"{self['screen_name']}的关注信息已更新完毕\n\n")
                break
            cards_ = js['data']['cards'][0]['card_group']
            users = [card['following'] for card in cards_ if card['card_type'] == 10]
            for user in users:
                no_key = ['cover_image_phone', 'profile_url', 'profile_image_url']
                user = {k: v for k, v in user.items() if v and k not in no_key}
                if user.get('remark'):
                    user['screen_name'] = user.pop('remark')
                user['homepage'] = f'https://weibo.com/u/{user["id"]}'
                if user['gender'] == 'f':
                    user['gender'] = 'female'
                    yield user
                    sleep(1)
            logger.success(f'{self["screen_name"]}的页面{page}已获取完毕')
            pause(mode='page')

    def weibos(self):
        page = 0
        while True:
            page += 1
            pause(mode='pause')
            js = get_json(containerid=f"107603{self['id']}", page=page)
            mblogs = [w['mblog'] for w in js['data']['cards'] if w['card_type'] == 9]
            if not mblogs:
                assert not js['ok']
                logger.warning(
                    f"not js['ok'], seems reached end, no wb return for page {page}")
                break

            for weibo_info in mblogs:
                if weibo_info.get('retweeted_status'):
                    continue
                weibo = Weibo.from_weibo_info(weibo_info)
                yield weibo
            logger.success(f"++++++++页面 {page} 获取完毕++++++++++\n")

    def save_avatar(self, download_dir=None):
        url = self['avatar_hd']
        downloaded = requests.get(url, headers=headers).content
        if download_dir:
            download_dir.mkdir(parents=True)
            basename = f"{self['id']}-{self['screen_name']}"
            ext = Path(url).ext
            filepath = Path(download_dir, basename + ext)
            if filepath.exists():
                logger.warning(f'{filepath} already exists')
            else:
                filepath.write_file(downloaded, 'wb')
        return downloaded


def _user_info_fix(user_info):
    user_info = user_info.copy()
    if '昵称' in user_info:
        assert user_info.get('screen_name', '') == user_info.pop('昵称', '')
    if '简介' in user_info:
        assert user_info.get('description', '') == user_info.pop('简介', '').replace('暂无简介', '')
    if 'Tap to set alias' in user_info:
        assert user_info.get('remark', '') == user_info.pop('Tap to set alias', '')
    if user_info.get('gender') == 'f':
        assert user_info.pop('性别') == '女'
        user_info['gender'] = 'female'
    elif user_info.get('gender') == 'm':
        assert user_info.pop('性别') == '男'
        user_info['gender'] = 'female'

    if '所在地' in user_info:
        assert 'location' not in user_info or user_info['location'] == user_info['所在地']
        user_info['location'] = user_info.pop('所在地')
    if '生日' in user_info:
        assert 'birthday' not in user_info or user_info['birthday'] == user_info['生日']
        user_info['birthday'] = user_info.pop('生日')
    user_info.pop('cover_image_phone', '')
    user_info.pop('profile_image_url', '')
    user_info.pop('profile_url', '')
    if birthday := user_info.get('birthday'):
        birthday = birthday.split()[0].strip()
        if re.match(r'\d{4}-\d{2}-\d{2}', birthday):
            age = pendulum.parse(birthday).diff().years
            user_info['birthday'] = birthday
            user_info['age'] = age

    if 'education' not in user_info:
        keys = ['大学', '海外', '高中']
        edu_info = [x for k in keys if (x := user_info.pop(k, ''))]
        user_info['education'] = '; '.join(edu_info)

    if not user_info.get('close_blue_v'):
        user_info.pop('close_blue_v', '')

    return user_info
