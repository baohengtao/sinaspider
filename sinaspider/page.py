import itertools
import re
from time import sleep
from typing import Iterator

import pendulum
from requests import JSONDecodeError

from sinaspider import console
from sinaspider.helper import fetcher
from sinaspider.parser import WeiboParser


class SinaBot:
    def __init__(self, art_login=False) -> None:
        self.art_login = art_login
        self.sess = fetcher.sess_art if self.art_login else fetcher.sess_main
        url = (
            "https://api.weibo.cn/2/profile/me?launchid=10000365--x&from=10D9293010&c=iphone")
        s = '694a9ce0' if self.art_login else '537c037e'
        js = fetcher.get(url, art_login=self.art_login, params={'s': s}).json()
        screen_name = js['mineinfo']['screen_name']
        console.log(f'current logined as {screen_name}')

    def set_remark(self, uid, remark):
        url = "https://api.weibo.cn/2/friendships/remark/update"
        data = {
            "uid": uid,
            "remark": remark,
            "c": "weicoabroad",
            "s": "c773e7e0",
        }
        response = self.sess.post(url,  data=data)
        response.raise_for_status()

    def follow(self, uid):
        url = "https://api.weibo.cn/2/friendships/create"
        data = {
            "c": "weicoabroad",
            "from": "12CC293010",
            "s": "99312000",
            "uid": uid
        }
        r = self.sess.post(url, data=data)
        r.raise_for_status()
        js = r.json()
        if (errmsg := js.get('errmsg')) == '该用户不存在':
            console.log(f'{errmsg} (https://weibo.com/u/{uid})')
            return
        elif errmsg:
            raise ValueError(js)
        url = ('https://m.weibo.cn/api/container/getIndex?'
               f'containerid=100505{uid}')
        js = fetcher.get(url, art_login=self.art_login).json()
        user_info = js['data']['userInfo']
        assert user_info['following'] is True
        user = f'{user_info["screen_name"]} (https://weibo.com/u/{uid}) '
        console.log(f'following {user} successfully')

    def unfollow(self, uid):
        url = 'https://api.weibo.cn/2/friendships/destroy'
        s = '0726b708'  # for art_login
        data = {
            'c': 'weicoabroad',
            's': s,
            'uid': uid,
        }
        response = self.sess.post(url,  data=data)
        response.raise_for_status()
        js = response.json()
        if js.get('errmsg') == 'not followed':
            console.log(f'{uid} alread unfollowed', )
        else:
            assert js['following'] is False
            console.log(
                f'{js["screen_name"]} (https://weibo.com/u/{uid}) unfollowed')

    def get_following_list(self, pages=None):
        s = '0726b708' if self.art_login else 'c773e7e0'
        url = ('https://api.weibo.cn/2/cardlist?c=weicoabroad'
               f'&containerid=231093_-_selffollowed&page=%s&s={s}')
        cnt = 0
        if pages is None:
            pages = itertools.count(start=1)
        for page in pages:
            r = fetcher.get(url % page, art_login=self.art_login)
            cards = r.json()['cards']
            if page == 1:
                if cards[-1].get('name') == '没有更多内容了':
                    cards.pop()
                elif cards[-1].get('desc') == '来这里可以关注更多有意思的人':
                    console.log('seems no following...')
                    break
                cards = cards[-1]
            else:
                cards = cards[0]
            if cards.get("name") == "没有更多内容了":
                console.log(f'{cnt} following fetched')
                break
            cards = cards['card_group']
            keys = ['id', 'screen_name', 'remark']
            console.log(f'{len(cards)} cards find on page {page}')
            for card in cards:
                assert card['card_type'] == 10
                user = card['user']
                user = {k: user[k] for k in keys}
                yield user
                cnt += 1

    def get_friends_list(self):

        s = 'c773e7e0'  # if self.art_login is False
        url = ('https://api.weibo.cn/2/friendships/bilateral?c=weicoabroad'
               f'&real_relationships=1&s={s}&trim_status=1&page=%s')
        cnt = 0
        for page in itertools.count(start=1):
            r = fetcher.get(url % page, art_login=self.art_login)
            js = r.json()
            if not (users := js['users']):
                console.log(f'{cnt} friends fetched')
                break
            console.log(f'{len(users)} users find on page {page}')
            keys = ['id', 'screen_name', 'remark']
            for user in users:
                yield {k: user[k] for k in keys}
                cnt += 1


class Page:
    def __init__(self, user_id: int) -> None:
        self.id = user_id

    def homepage(self, start_page: int = 1,
                 parse: bool = True) -> Iterator[dict]:
        """
        Fetch user's homepage weibo.

        Args:
                start_page: the start page to fetch
                parse: whether to parse weibo, default True
        """
        url = ('https://m.weibo.cn/api/container/getIndex'
               f'?containerid=107603{self.id}&page=%s')
        for page in itertools.count(start=max(start_page, 1)):
            for try_time in itertools.count(start=1):
                if (js := fetcher.get(url % page).json())['ok']:
                    break
                if js['msg'] == '请求过于频繁，歇歇吧':
                    raise ConnectionError(js['msg'])
                if try_time > 3:
                    console.log(
                        "not js['ok'], seems reached end, no wb return for "
                        f"page {page}", style='warning')
                    return

            mblogs = [card['mblog'] for card in js['data']['cards']
                      if card['card_type'] == 9]

            for weibo_info in mblogs:
                if weibo_info['user']['id'] != self.id:
                    assert '评论过的微博' in weibo_info['title']['text']
                    continue
                if weibo_info['source'] == '生日动态':
                    continue
                if 'retweeted_status' in weibo_info:
                    continue
                yield WeiboParser(weibo_info).parse() if parse else weibo_info
            else:
                console.log(
                    f"++++++++ 页面 {page} 获取完毕 ++++++++++\n")

    @staticmethod
    def timeline(since: pendulum.DateTime):
        """Get status on my timeline."""
        next_cursor = None
        # seed = 'https://m.weibo.cn/feed/friends'
        seed = 'https://api.weibo.cn/2/statuses/friends_timeline?feature=1&c=weicoabroad&from=12CC293010&i=f185221&s=b59fafff'
        while True:
            url = f'{seed}&max_id={next_cursor}' if next_cursor else seed
            while True:
                r = fetcher.get(url)
                try:
                    data = r.json()
                except JSONDecodeError:
                    console.log(
                        f'{r.url} json decode error', style='error')
                    console.log('sleeping 60 seconds')
                    sleep(60)
                else:
                    break
            next_cursor = data['next_cursor']
            created_at = None
            for status in data['statuses']:
                assert 'retweeted_status' not in status
                created_at = pendulum.parse(status['created_at'], strict=False)
                if created_at < since:
                    return

                if status.get('pic_ids'):
                    yield status
                elif status.get('page_info', {}).get('type') == 'video':
                    yield status
            console.log(f'created_at:{created_at}')

    def _liked_card(self) -> Iterator[dict]:
        url = ('https://api.weibo.cn/2/cardlist?c=weicoabroad&containerid='
               f'230869{self.id}-_mix-_like-pic&page=%s&s=c773e7e0')
        for page in itertools.count(start=1):
            console.log(f'Fetching liked weibo page {page}...')
            while True:
                if (r := fetcher.get(url % page)).status_code != 200:
                    console.log(
                        f'{r.url} get status code {r.status_code}...',
                        style='warning')
                elif 'cards' in (js := r.json()):
                    break
                elif js.get('errmsg') == 'attitude: user status wrong':
                    raise ValueError(f'attitude: user {self.id} status wrong')
                else:
                    console.log(f'{r.url} get js error: {js}', style='error')
                console.log('sleeping 60 seconds')
                sleep(60)

            if (cards := js['cards']) is None:
                console.log(
                    f"js[cards] is None for [link={r.url}]r.url[/link]",
                    style='warning')
                break
            mblogs = _yield_from_cards(cards)
            yield from mblogs

    def liked(self, parse: bool = True) -> Iterator[dict]:
        """
        Fetch user's liked weibo.

        Args:
                parse: whether to parse weibo, default True
        """
        for weibo_info in self._liked_card():
            if weibo_info.get('deleted') == '1':
                continue
            if weibo_info['pic_num'] == 0:
                continue
            user_info = weibo_info['user']
            if user_info['gender'] == 'm':
                continue
            if parse:
                try:
                    yield WeiboParser(weibo_info).parse(online=False)
                except (KeyError, AttributeError):
                    console.log(
                        "parse weibo_info failed for "
                        f"https://m.weibo.cn/status/{weibo_info['id']}",
                        style='error')
            else:
                yield weibo_info

    def friends(self, parse=True):
        """Get user's friends."""
        pattern = (r'(https://tvax?\d\.sinaimg\.cn)/'
                   r'(?:crop\.\d+\.\d+\.\d+\.\d+\.\d+\/)?(.*?)\?.*$')
        friend_count = 0
        for page in itertools.count(start=1):
            url = ("https://api.weibo.cn/2/friendships/bilateral?"
                   f"c=weicoabroad&page={page}&s=c773e7e0&uid={self.id}")
            js = fetcher.get(url).json()
            if not (users := js['users']):
                console.log(
                    f"{friend_count} friends fetched "
                    f"(total_number: {js['total_number']})")
                break
            for raw in users:
                info = {
                    'user_id': self.id,
                    'friend_id': (friend_id := raw['id']),
                    'friend_name': raw['screen_name'],
                    'gender': raw['gender'],
                    'location': raw['location'],
                    'description': raw['description'],
                    'homepage': f'https://weibo.com/u/{friend_id}',
                    'statuses_count': raw['statuses_count'],
                    'followers_count': raw['followers_count'],
                    'follow_count': raw['friends_count'],
                    'bi_followers_count': raw['bi_followers_count'],
                    'following': raw['following'],
                }
                info['created_at'] = pendulum.from_format(
                    raw['created_at'], 'ddd MMM DD HH:mm:ss Z YYYY')
                p1, p2 = re.match(pattern, raw['avatar_hd']).groups()
                info['avatar_hd'] = f'{p1}/large/{p2}'
                yield info if parse else raw
                friend_count += 1

    @staticmethod
    def _get_page_post_on(js: dict):
        mblogs = [card['mblog'] for card in js['data']['cards']
                  if card['card_type'] == 9]
        while mblogs:
            mblog = mblogs.pop()
            if '评论过的微博' in mblog.get('title', {}).get('text', ''):
                continue
            if mblog['source'] == '生日动态':
                continue
            return WeiboParser(mblog).parse(online=False)['created_at']

    def get_visibility(self) -> bool:
        """判断用户是否设置微博半年内可见."""
        url = ('https://m.weibo.cn/api/container/getIndex'
               f'?containerid=107603{self.id}&page=%s')
        start, end = 1, 4
        while (js := fetcher.get(url % end).json())['ok']:
            post_on = self._get_page_post_on(js)
            if (days := post_on.diff().days) > 186:
                return True
            start = end + 1
            end = min(max(end + 3, end * 180 // days), end * 2)
            console.log(f'checking page {(start, end)}...'
                        f'to get visibility (days:{days})')
        else:
            end -= 1

        while start <= end:
            mid = (start + end) // 2
            console.log(f'checking page {mid}...to get visibility')
            if not (js := fetcher.get(url % mid).json())['ok']:
                end = mid - 1
            elif not (post_on := self._get_page_post_on(js)):
                assert mid == 1
                return False
            elif post_on < pendulum.now().subtract(months=6, days=5):
                return True
            else:
                start = mid + 1
        return False


def _yield_from_cards(cards):
    for card in cards:
        if card['card_type'] == 9:
            yield card['mblog']
        elif card['card_type'] == 11:
            yield from _yield_from_cards(card['card_group'])
