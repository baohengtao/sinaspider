import json
import re
from collections import OrderedDict
from datetime import timedelta
from functools import partial
from pathlib import Path
from time import sleep
from typing import Union, Generator
from itertools import  chain

import pendulum
from bs4 import BeautifulSoup
from tqdm import trange

from sinaspider.helper import get_url, logger, pause, get_config, weibo_api_url, write_xmp
from sinaspider.weibo import get_weibo_pages


class Owner:
    def __init__(self):
        account_id = get_config().as_int('account_id')
        self.info = User(account_id)
        self.weibos = self.info.weibos
        self.following = self.info.following
        self.collection = partial(get_weibo_pages, containerid=230259)


class User(OrderedDict):
    from sinaspider.database import user_table as table
    from sinaspider.database import relation_table
 
    def __init__(self, *args, **kwargs):
        if kwargs or args[1:] or not isinstance(args[0], int):
            super().__init__(*args, **kwargs)
        else:
            super().__init__(self.from_user_id(args[0]))
        self.weibos = partial(
            get_weibo_pages, containerid=f"107603{self['id']}")
        self.following = partial(
            get_follow_pages, f'231051_-_followers_-_{self["id"]}')

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
        docu = cls.table.find_one(id=user_id) or {}
        if offline is None:
            offline = False
            if docu and (updated := docu.get('info_updated_at')):
                # 若最近15天更新过, 则 offline 为 True
                offline = (pendulum.instance(updated).diff().days < 15)
        if offline is False:
            logger.info('update online...')
            fetch_user_info(user_id)
            docu = cls(cls.table.find_one(id=user_id))
            print(docu)
        docu = cls((k, v) for k, v in docu.items() if v)
        return docu

    def update_table(self):
        self.table.upsert(self, ['id'])

    def relation(self, friends_only=True, cache_days=30):
        logger.info('正在获取关注页面')
        follow = get_follow_pages(
            f'231051_-_followers_-_{self["id"]}', cache_days)
        follow = {u['id'] for u in follow}
        logger.info(f"共获取 {len(follow)}/{self['follow_count']} 个关注")

        fans = get_follow_pages(f'231051_-_fans_-_{self["id"]}', cache_days)
        fans = {u['id'] for u in fans}
        logger.info(f"共获取 {len(fans)}/{self['followers_count']} 个粉丝")
        friends = fans & follow
        logger.info(f'共发现{len(friends)}个好友')
        for uid in follow:
            if friends_only and uid not in friends:
                continue
            following = self.__class__(uid)
            following['follower'] = self['id']
            following['follower_name'] = self['screen_name']
            following['following'] = following.pop('id')
            following['is_friends'] = uid in friends
            self.relation_table.upsert(following, ['follower', 'following'])

    def __str__(self):
        text = ''
        keys = ['id', 'screen_name', 'gender', 'birthday', 'location', 'homepage',
                'description', 'statuses_count', 'followers_count', 'follow_count']
        for k in keys:
            if v := self.get(k):
                text += f'{k}: {v}\n'
        return text

    def save_avatar(self, download_dir=None):
        """保存用户头像"""
        url = self['avatar_hd']
        downloaded = get_url(url).content
        download_dir = Path(download_dir) if download_dir else get_config()['download_dir']
        download_dir.mkdir(parents=True, exist_ok=True)
        basename = f"{self['id']}-{self['screen_name']}"
        ext = Path(url).suffix
        filepath = Path(download_dir) / (basename + ext)
        if filepath.exists():
            logger.warning(f'{filepath} already exists')
        else:
            filepath.write_bytes(downloaded)
            tags = {'XMP:Artist': self['screen_name'], 'XMP:BlogURL':self['homepage']}
            write_xmp(tags, filepath)
            logger.success(f'save avatar at  {filepath}')
        return downloaded


def get_follow_pages(containerid: Union[str, int], cache_days=30) -> Generator[dict, None, None]:
    """
    获取关注列表

    Args:
        containerid (Union[str, int]):
            - 用户的关注列表: f'231051_-_followers_-_{user_id}' 
        cache_days: 页面缓冲时间时间, 若为0, 则不缓存

    Yields:
        Generator[dict]: 返回用户字典
    """
    page = 1
    while True:
        url = weibo_api_url.set(args={'containerid': containerid})
        if 'fans' in containerid:
            url.args['since_id'] = 21 * page - 1
        else:
            url.args['page'] = page
        response = get_url(url, expire_after=timedelta(days=cache_days))
        js = response.json()
        if not js['ok']:
            if js['msg'] == '请求过于频繁，歇歇吧':
                response.revalidate(0)
                for i in trange(1800, desc='sleeping...'):
                    sleep(i / 4)
            else:
                logger.success(f"关注信息已更新完毕")
                logger.info(f'js==>{js}')
                break
        cards_ = js['data']['cards'][0]['card_group']

        users = [card.get('following') or card.get('user')
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
        if not response.from_cache:
            pause(mode='page')
        page += 1


def fetch_user_info(uid: int, cache_days=30) -> User:
    expire_after = timedelta(days=cache_days)
    url = weibo_api_url.copy()

    # 获取来自m.weibo.com的信息
    logger.info(f'fetching extra user info for {uid}')
    url.args = {'containerid': f"230283{uid}_-_INFO"}
    respond_card = get_url(url, expire_after)
    user_card = _parse_user_card(respond_card)

    # 获取主信息
    logger.info(f'fetching  user info for {uid}')
    url.args = {'containerid': f"100505{uid}"}
    respond_info = get_url(url, expire_after)
    js = json.loads(respond_info.content)
    logger.info(url)
    user_info = js['data']['userInfo']
    user_info.pop('toolbar_menus', '')

    # 获取来自cn的信息
    respond_cn = get_url(f'https://weibo.cn/{uid}/info', expire_after)
    user_cn = _parse_user_cn(respond_cn)

    # 合并信息
    user = user_card | user_cn | user_info
    s = {(k, str(v)) for k, v in  chain.from_iterable([user_card.items(), user_cn.items(), user_info.items()])}
    assert s.issubset({(k, str(v)) for k, v in user.items()})
    user = _user_info_fix(user)
    user['info_updated_at'] = pendulum.now()
    user = User(user)
    user.update_table()

    from_cache = [r.from_cache for r in [respond_card, respond_cn, respond_info]]
    assert min(from_cache) is max(from_cache)
    if not all(from_cache):
        logger.info(f"{user['screen_name']} 信息已从网络获取.")
        pause(mode='page')
    else:
        logger.info(f"{user['screen_name']} 信息已从缓存读取.")
    return user


# noinspection PyUnresolvedReferences
def _user_info_fix(user_info: dict) -> OrderedDict:
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
        user_info['gender'] = 'male'

    # pop items
    keys = ['cover_image_phone', 'profile_image_url', 'profile_url']
    for key in keys:
        user_info.pop(key, '')

    # merge location
    keys = ['location', '地区', '所在地']
    values = [user_info.pop(k, '') for k in keys]
    values = [v for v in values if v]
    if values:
        assert len(set(values)) == 1
        user_info[keys[0]] = values[0]

    # merge verified_reason
    keys = ['verified_reason', '认证', '认证信息']
    values = [user_info.pop(k, '') for k in keys]
    values = [v for v in values if v]
    if values:
        if not len(set(values)) == 1:
            logger.error(set(values))
            assert False
        user_info[keys[0]] = values[0]

    if '生日' in user_info:
        assert 'birthday' not in user_info or user_info['birthday'] == user_info['生日']
        user_info['birthday'] = user_info.pop('生日')
    if birthday := user_info.get('birthday'):
        birthday = birthday.split()[0].strip()
        if birthday == '0001-00-00':
            pass
        elif re.match(r'\d{4}-\d{2}-\d{2}', birthday):
            try:
                age = pendulum.parse(birthday).diff().years
                user_info['age'] = age
            except pendulum.parsing.ParserError:
                logger.warning(f'Cannot parse birthday {birthday}')
            user_info['birthday'] = birthday
    if education := user_info.pop('学习经历', ''):
        assert 'education' not in user_info
        for key in ['大学', '海外', '高中', '初中', '中专技校']:
            assert user_info.pop(key, '') in ' '.join(education)
        user_info['education'] = education

    user_info['homepage'] = f'https://weibo.com/u/{user_info["id"]}'
    user_info = {k: v for k, v in user_info.items() if v or v == 0}
    user_info['hometown'] = user_info.pop('家乡', '')

    key_order = [
        'id', 'screen_name', 'remark', 'birthday', 'age', 'education', 'gender',
        'location', 'description', 'homepage', 'statuses_count',
        'following', 'follow_me', 'followers_count', 'follow_count'
    ]
    user_info_ordered = OrderedDict()
    for key in key_order:
        if key in user_info:
            user_info_ordered[key] = user_info.pop(key)
    user_info_ordered.update(user_info)

    return user_info_ordered


def _parse_user_cn(respond):
    """解析weibo.cn的内容"""
    soup = BeautifulSoup(respond.text, 'lxml')
    divs = soup.find_all('div')
    infos = dict()
    for tip, c in zip(divs[:-1], divs[1:]):
        if tip.attrs['class'] == ['tip']:
            assert c.attrs['class'] == ['c']
            if tip.text == '其他信息':
                continue
            if tip.text == '基本信息':
                for line in str(c).split('<br/>'):
                    if text := BeautifulSoup(line, 'lxml').text:
                        text = text.replace('\xa0', ' ')
                        try:
                            key, value = re.split('[:：]', text, maxsplit=1)
                            infos[key] = value
                        except ValueError as e:
                            logger.error(f'{text} cannot parsed')
                            raise e

            elif tip.text == '学习经历' or '工作经历':
                education = c.text.replace('\xa0', ' ').split('·')
                infos[tip.text] = [e.strip() for e in education if e]
            else:
                infos[tip.text] = c.text.replace('\xa0', ' ')

    if infos.get('生日') == '01-01':
        infos.pop('生日')
    return infos


def _parse_user_card(respond_card):
    user_card = respond_card.json()['data']['cards']
    user_card = sum([c['card_group'] for c in user_card], [])
    user_card = {card['item_name']: card['item_content']
                 for card in user_card if 'item_name' in card}
    if '生日' in user_card:
        user_card['生日'] = user_card['生日'].split()[0]
    return user_card
