import re
from pathlib import Path
from bs4 import  BeautifulSoup

import pendulum

from sinaspider.helper import get_json, get_url, logger, pause, pg
from sinaspider.weibo import get_weibo_pages

USER_TABLE = 'user'
user_table = pg[USER_TABLE]


def get_follow_pages(containerid, start_page=1):
    page = start_page
    while True:
        js = get_json(containerid=containerid, page=page)
        if not js['ok']:
            logger.success(f"关注信息已更新完毕")
            break
        cards_ = js['data']['cards'][0]['card_group']
        users = [card['following']
                 for card in cards_ if card['card_type'] == 10]
        for user in users:
            no_key = ['cover_image_phone',
                      'profile_url', 'profile_image_url']
            user = {k: v for k, v in user.items() if v and k not in no_key}
            if user.get('remark'):
                user['screen_name'] = user.pop('remark')
            user['homepage'] = f'https://weibo.com/u/{user["id"]}'
            if user['gender'] == 'f':
                user['gender'] = 'female'
            elif user['gender'] == 'm':
                user['gender'] = 'male'
            yield user
        logger.success(f'页面 {page} 已获取完毕')
        pause(mode='page')
        page += 1


class Owner:
    @staticmethod
    def get_favor_pages():
        return get_weibo_pages(containerid=230259)

    @staticmethod
    def get_weibo_pages():
        pass


class User(dict):

    @classmethod
    def from_user_id(cls, user_id, offline=None):
        """
        根据用户 id 获取用户信息.
        若用户信息从网络上获取, 则对数据库中的用户信息进行更新.

        Args:
            user_id (int)
            offline (bool or None):
                - None(default): 若用户信息最近 15 天内更新过, 则 offline 为 True, 否则 offline 为 False
                - True: 从数据库获取用户信息
                - False: 从网络获取用户信息并更新数据库

        Returns:
            User(dict): 用户信息
        """

        docu = user_table.find_one(id=user_id) or {}
        if offline is None:
            offline = False
            if docu and (updated := docu.get('updated')):
                # 若最近15天更新过, 则 offline 为 True
                offline = (pendulum.instance(updated).diff().days < 15)

        if offline is True:
            return cls(docu)
        else:
            assert offline is False
            user = fetch_user_info(user_id)
            user_table.upsert(user, ['id'])
            return cls(user)

    def following(self, start_page=1):
        containerid = f'231051_-_followers_-_{self["id"]}'
        return get_follow_pages(containerid, start_page)

    def weibos(self, start_page=1):
        containerid = f"107603{self['id']}"
        return get_weibo_pages(containerid, start_page)

    def print(self):
        """打印用户信息"""
        keys = ['id', 'screen_name', 'gender', 'birthday', 'location', 'homepage',
                'description', 'statuses_count', 'followers_count', 'follow_count']

        logger.info('+' * 100)
        for k in keys:
            if v := self.get(k):
                logger.info(f'{k}: {v}')
        logger.info('+' * 100)

    def save_avatar(self, download_dir=None):
        """保存用户头像"""
        url = self['avatar_hd']
        downloaded = get_url(url).content
        if download_dir:
            download_dir.mkdir(parents=True)
            basename = f"{self['id']}-{self['screen_name']}"
            ext = Path(url).suffix
            filepath = Path(download_dir) / (basename + ext)
            if filepath.exists():
                logger.warning(f'{filepath} already exists')
            else:
                filepath.write_bytes(downloaded)
        return downloaded

def fetch_user_info(user_id):
    extra = _get_user_extra(user_id)
    info = _get_user_info(user_id)
    assert extra | info == info | extra
    user = _user_info_fix(extra | info)
    user['updated'] = pendulum.now()
    # 获取用户数据
    logger.info(f"{user['screen_name']} 信息已获取.")
    pause(mode='page')
    return user

def _get_user_extra(user_id):
     
    def _get_user_cn(user_id):
        html = get_url(f'https://weibo.cn/{user_id}/info')
        soup = BeautifulSoup(html.text, 'lxml')
        divs = soup.find_all('div')
        infos = dict()
        for tip, c in zip(divs[:-1], divs[1:]):
            if tip.attrs['class'] == ['tip']:
                assert c.attrs['class'] == ['c']
                if tip.text == '其他信息':
                    continue
                elif tip.text == '基本信息':
                    basic_info = c.get_text(separator='\n').splitlines()
                    basic_info = [item.split(':') for item in basic_info]
                    infos.update(v for v in basic_info if len(v)==2)
                elif tip.text == '学习经历' or '工作经历':
                    education = c.text.replace('\xa0', ' ').split('·')
                    infos[tip.text] = [e.strip() for e in education if e]
                else:
                    infos[tip.text] = c.text
        return infos
        
    

    def _get_user_cards(user_id):
        user_cards = get_json(containerid=f"230283{user_id}_-_INFO")
        user_cards = user_cards['data']['cards']
        user_cards = sum([c['card_group'] for c in user_cards], [])
        user_cards = {card['item_name']: card['item_content']
                        for card in user_cards if 'item_name' in card}
        user_cards['生日'] = user_cards['生日'].split()[0]
        return user_cards
    
    x, y = _get_user_cards(user_id), _get_user_cn(user_id)
    assert x | y == y | x
    
    return x | y    

def _get_user_info(user_id):
    user_info = get_json(containerid=f"100505{user_id}")
    user_info = user_info['data']['userInfo']

    user_info.pop('toolbar_menus')
    return user_info

    

def _user_info_fix(user_info: dict) -> dict:
    """清洗用户信息."""
    user_info = user_info.copy()
    if '昵称' in user_info:
        assert user_info.get('screen_name', '') == user_info.pop('昵称', '')
    if '简介' in user_info:
        assert user_info.get('description', '') == user_info.pop(
            '简介', '').replace('暂无简介', '')
    if 'Tap to set alias' in user_info:
        assert user_info.get('remark', '') == user_info.pop(
            'Tap to set alias', '')
    if user_info.get('gender') == 'f':
        assert user_info.pop('性别') == '女'
        user_info['gender'] = 'female'
    elif user_info.get('gender') == 'm':
        assert user_info.pop('性别') == '男'
        user_info['gender'] = 'female'
        
    # pop items
    keys = ['cover_image_phone', 'profile_image_url', 'profile_url'] 
    for key in keys:
        user_info.pop(key, '')
    
    # merge location
    keys = ['地区', 'location', '所在地']
    values = [user_info.pop(k, '') for k in keys]
    values = [v for v in values if v]
    if values:
        assert len(set(values)) == 1
        user_info['location'] = values[0]

    if '生日' in user_info:
        assert 'birthday' not in user_info or user_info['birthday'] == user_info['生日']
        user_info['birthday'] = user_info.pop('生日')
    if birthday := user_info.get('birthday'):
        birthday = birthday.split()[0].strip()
        if re.match(r'\d{4}-\d{2}-\d{2}', birthday):
            age = pendulum.parse(birthday).diff().years
            user_info['birthday'] = birthday
            user_info['age'] = age
     
    if education:=user_info.pop('学习经历', ''):
        assert 'education' not in user_info
        for key in  ['大学', '海外', '高中']:
            assert user_info.pop(key, '') in ' '.join(education)
        user_info['education'] = education


    user_info['homepage'] = f'https://weibo.com/u/{user_info["id"]}'
    user_info = {k: v for k, v in user_info.items() if v or v == 0}
    return user_info
