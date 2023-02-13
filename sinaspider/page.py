import itertools
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Iterator

import pendulum

from sinaspider import console
from sinaspider.helper import get_url, pause, weibo_api_url
from sinaspider.parser import WeiboParser


class Page:
    def __init__(self, user_id) -> None:
        self.id = user_id

    def friends(self):

        for page in itertools.count():
            url = ("https://api.weibo.cn/2/friendships/bilateral?"
                   f"c=weicoabroad&page={page}&s=c773e7e0&uid={self.id}")
            js = get_url(url).json()
            if not (users := js['users']):
                break
            yield from users
            pause(mode='page')

    @staticmethod
    def timeline(since: pendulum.DateTime = None):
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

    def liked(self, since: datetime) -> Iterator[dict]:
        """
        获取用户点赞的微博
        """
        from sinaspider.helper import normalize_str
        url = ('https://api.weibo.cn/2/cardlist?c=weicoabroad&containerid='
               f'230869{self.id}-_mix-_like-pic&page=%s&s=c773e7e0')
        for page in itertools.count(start=1):
            while (r := get_url(url % page)).status_code != 200:
                console.log(
                    f'{r.url} get status code {r.status_code}...',
                    style='error')
                console.log('sleeping 60 seconds')
                sleep(60)
            js = r.json()
            if (cards := js['cards']) is None:
                console.log(
                    f"js[cards] is None for [link={r.url}]r.url[/link]",
                    style='error')
                break
            mblogs = _yield_from_cards(cards)
            for weibo_info in mblogs:
                if weibo_info.get('deleted') == '1':
                    continue

                weibo = WeiboParser(weibo_info).parse(online=False)

                if "photos" in weibo and weibo['gender'] != 'm':
                    followers_count = int(
                        normalize_str(weibo['followers_count']))
                    if followers_count > 20000 or followers_count < 500:
                        continue
                    if weibo['created_at'] < since:
                        console.log(
                            f"时间 {weibo['created_at']:%y-%m-%d}"
                            f"在 {since:%y-%m-%d} 之前, 获取完毕")
                        return
                    if _check_liked(weibo['id']):
                        yield weibo

            pause(mode='page')

    def homepage(self,
                 since: datetime = pendulum.from_timestamp(0),
                 start_page=1) -> Iterator[dict]:
        """
        爬取用户主页的微博
        """
        yield from self._weibo_pages(
            f"107603{self.id}", since=since, start_page=start_page)

    @staticmethod
    def _weibo_pages(containerid: str,
                     since: datetime = pendulum.from_timestamp(0),
                     start_page: int = 1,
                     ) -> Iterator[dict]:
        """
        爬取某一 containerid 类型的所有微博

        Args:
            containerid(str):
                - 获取用户页面的微博: f"107603{user_id}"
                - 获取收藏页面的微博: 230259
            start_page(int): 指定从哪一页开始爬取, 默认第一页.
            since: 若为整数, 从哪天开始爬取, 默认所有时间


        Yields:
            Generator[Weibo]: 生成微博实例
        """
        since = pendulum.instance(since)
        console.log(f'fetch weibo from {since:%Y-%m-%d}\n')
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
                weibo = WeiboParser(weibo_info).parse()
                if weibo['is_comment']:
                    console.log(f'发现评论过的微博， 略过...{weibo}',
                                style='warning')
                    continue
                if (created_at := weibo['created_at']) < since:
                    if weibo['is_pinned']:
                        console.log("略过置顶微博...")
                        continue
                    else:
                        console.log(
                            f"时间 {created_at:%y-%m-%d} 在 {since:%y-%m-%d}之前, "
                            "获取完毕")
                        return
                if 'retweeted' not in weibo:
                    yield weibo
            else:
                console.log(
                    f"++++++++ 页面 {url.args['page']} 获取完毕 ++++++++++\n")
                pause(mode='page')


def _check_liked(weibo_id):
    from peewee import BigIntegerField, Model, SqliteDatabase
    database = SqliteDatabase(Path.home() / ".cache/liked_weibo.db")

    class BaseModel(Model):
        class Meta:
            database = SqliteDatabase(Path.home() / ".cache/liked_weibo.db")

    class LikedWeibo(BaseModel):
        weibo_id = BigIntegerField()

    database.create_tables([LikedWeibo])

    if LikedWeibo.get_or_none(weibo_id=weibo_id):
        console.log(f'{weibo_id} already in {database.database}',
                    style='error')
        return False
    else:
        return True


def _yield_from_cards(cards):
    for card in cards:
        if card['card_type'] == 9:
            yield card['mblog']
        elif card['card_type'] == 11:
            yield from _yield_from_cards(card['card_group'])
