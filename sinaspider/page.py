import itertools
from datetime import datetime
from time import sleep
from typing import Iterator

import pendulum

from sinaspider import console
from sinaspider.helper import get_url, pause, weibo_api_url
from sinaspider.parser import WeiboParser


class Page:
    def __init__(self, user_id: int) -> None:
        self.id = user_id

    def friends(self):
        """get user's friends"""
        for page in itertools.count():
            url = ("https://api.weibo.cn/2/friendships/bilateral?"
                   f"c=weicoabroad&page={page}&s=c773e7e0&uid={self.id}")
            js = get_url(url).json()
            if not (users := js['users']):
                break
            yield from users
            pause(mode='page')

    @staticmethod
    def timeline(since: pendulum.DateTime):
        """get status on my timeline"""
        next_cursor = None
        seed = 'https://m.weibo.cn/feed/friends'
        while True:
            url = f'{seed}?max_id={next_cursor}' if next_cursor else seed
            r = get_url(url)
            data = r.json()['data']
            next_cursor = data['next_cursor']
            created_at = None
            for status in data['statuses']:
                created_at = pendulum.parse(status['created_at'], strict=False)
                if created_at < since:
                    return
                if 'retweeted_status' in status:
                    continue
                if status.get('pic_ids'):
                    yield status
            console.log(f'created_at:{created_at}')
            pause(mode='page')

    def _liked_card(self) -> Iterator[dict]:
        url = ('https://api.weibo.cn/2/cardlist?c=weicoabroad&containerid='
               f'230869{self.id}-_mix-_like-pic&page=%s&s=c773e7e0')
        for page in itertools.count(start=1):
            while (r := get_url(url % page)).status_code != 200:
                console.log(
                    f'{r.url} get status code {r.status_code}...',
                    style='warning')
                console.log('sleeping 60 seconds')
                sleep(60)
            js = r.json()
            if (cards := js['cards']) is None:
                console.log(
                    f"js[cards] is None for [link={r.url}]r.url[/link]",
                    style='warning')
                break
            mblogs = _yield_from_cards(cards)
            yield from mblogs
            pause(mode='page')

    def liked(self, parse: bool = True) -> Iterator[dict]:
        """
        fetch user's liked weibo.

        Args:
            parse: whether to parse weibo, default True
        """
        from sinaspider.helper import normalize_str
        for weibo_info in self._liked_card():
            if weibo_info.get('deleted') == '1':
                continue
            if weibo_info['pic_num'] == 0:
                continue
            user_info = weibo_info['user']
            if user_info['gender'] == 'm':
                continue
            followers_count = int(
                normalize_str(user_info['followers_count']))
            if followers_count > 50000 or followers_count < 500:
                continue
            if parse:
                yield WeiboParser(weibo_info).parse(online=False)
            else:
                yield weibo_info

    def homepage(self, start_page: int = 1, parse: bool = True) -> Iterator[dict]:
        """
        fetch user's homepage weibo

        Args:
            start_page: the start page to fetch
            parse: whether to parse weibo, default True
        """
        containerid = f"107603{self.id}",
        url = weibo_api_url.copy()
        url.args = {'containerid': containerid}
        for url.args['page'] in itertools.count(start=max(start_page, 1)):
            response = get_url(url)
            js = response.json()
            if not js['ok']:
                if js['msg'] == '请求过于频繁，歇歇吧':
                    raise ConnectionError(js['msg'])
                else:
                    console.log(
                        "not js['ok'], seems reached end, no wb return for "
                        f"page {url.args['page']}", style='warning')
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
                    f"++++++++ 页面 {url.args['page']} 获取完毕 ++++++++++\n")
                pause(mode='page')


def _yield_from_cards(cards):
    for card in cards:
        if card['card_type'] == 9:
            yield card['mblog']
        elif card['card_type'] == 11:
            yield from _yield_from_cards(card['card_group'])
