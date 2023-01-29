import itertools
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep
from typing import Generator

import pendulum
from tqdm import trange

from sinaspider import console
from sinaspider.helper import weibo_api_url, get_url, pause
from sinaspider.parser import parse_weibo


def get_friends_pages(uid):
    for page in itertools.count():
        url = f"https://api.weibo.cn/2/friendships/bilateral?c=weicoabroad&page={page}&s=c773e7e0&uid={uid}"
        js = get_url(url).json()
        if not (users := js['users']):
            break
        yield from users
        pause(mode='page')


def get_timeline_pages(since: pendulum.DateTime = None):
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


def check_liked(weibo_id):
    from peewee import SqliteDatabase, Model, BigIntegerField
    database = SqliteDatabase(Path.home() / ".cache/liked_weibo.db")

    class BaseModel(Model):
        class Meta:
            database = SqliteDatabase(Path.home() / ".cache/liked_weibo.db")

    class LikedWeibo(BaseModel):
        weibo_id = BigIntegerField()

    database.create_tables([LikedWeibo])

    if LikedWeibo.get_or_none(weibo_id=weibo_id):
        console.log(f'{weibo_id} already in {database.database}')
        return False
    else:
        # LikedWeibo.create(weibo_id=weibo_id)
        return True


def _yield_from_cards(cards):
    for card in cards:
        if card['card_type'] == 9:
            yield card['mblog']
        elif card['card_type'] == 11:
            yield from _yield_from_cards(card['card_group'])


def get_liked_pages(uid: int, since: datetime):
    from sinaspider.helper import normalize_str
    url = f'https://api.weibo.cn/2/cardlist?c=weicoabroad&containerid=230869{uid}-_mix-_like-pic&page=%s&s=c773e7e0'
    for page in itertools.count(start=1):
        while (r := get_url(url % page)).status_code != 200:
            console.log(
                f'{r.url} get status code {r.status_code}...', style='error')
            console.log('sleeping 60 seconds')
            sleep(60)
        js = r.json()
        if (cards := js['cards']) is None:
            console.log(f"js[cards] is None for [link={r.url}]r.url[/link]", style='error')
            break
        mblogs = _yield_from_cards(cards)
        for weibo_info in mblogs:
            if weibo_info.get('deleted') == '1':
                continue
            weibo = parse_weibo(weibo_info, offline=True)
            if "photos" in weibo and weibo['gender'] != 'm':
                followers_count = int(normalize_str(weibo['followers_count']))
                if followers_count > 20000 or followers_count < 500:
                    continue
                if weibo['created_at'] < since:
                    console.log(
                        f"时间{weibo['created_at']:%y-%m-%d} 在 {since:%y-%m-%d}之前, 获取完毕")
                    return
                if check_liked(weibo['id']):
                    yield weibo

        pause(mode='page')


def get_weibo_pages(containerid: str,
                    start_page: int = 1,
                    since: int | str | datetime = '1970-01-01',
                    ) -> Generator[dict, None, None]:
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
    if isinstance(since, int):
        assert since > 0
        since = pendulum.now().subtract(days=since)
    elif isinstance(since, str):
        since = pendulum.parse(since)
    else:
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
                    "not js['ok'], seems reached end, no wb return for page "
                    f"{url.args['page']}", style='warning')
                return

        mblogs = [card['mblog']
                  for card in js['data']['cards'] if card['card_type'] == 9]

        for weibo_info in mblogs:
            # if not (weibo := parse_weibo(weibo_info)):
            #     continue
            weibo = parse_weibo(weibo_info)
            if (created_at := weibo['created_at']) < since:
                if weibo['is_pinned']:
                    console.log("略过置顶微博...")
                    continue
                else:
                    console.log(
                        f"时间{created_at:%y-%m-%d} 在 {since:%y-%m-%d}之前, 获取完毕")
                    return
            if 'retweeted' not in weibo:
                yield weibo
        else:
            console.log(f"++++++++ 页面 {url.args['page']} 获取完毕 ++++++++++\n")
            pause(mode='page')


def get_follow_pages(containerid: str | int, cache_days=30) -> Generator[dict, None, None]:
    """
    获取关注列表

    Args:
        containerid (Union[str, int]):
            - 用户的关注列表: f'231051_-_followers_-_{user_id}'
        cache_days: 页面缓冲时间时间, 若为0, 则不缓存

    Yields:
        Iterator[dict]: 返回用户字典
    """
    url = weibo_api_url.set(args={'containerid': containerid})
    for url.args['page'] in itertools.count():
        if 'fans' in containerid:
            url.args['since_id'] = 21 * url.args.pop('page') - 1
        response = get_url(url, expire_after=timedelta(days=cache_days))
        js = response.json()
        if not js['ok']:
            if js['msg'] == '请求过于频繁，歇歇吧':
                response.revalidate(0)
                for i in trange(1800, desc='sleeping...'):
                    sleep(i / 4)
            else:
                console.print("关注信息已更新完毕")
                console.print(f'js==>{js}')
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
        if not response.from_cache and js['ok']:
            console.log(f'页面 {url.args["page"]} 已获取完毕')
        if not response.from_cache:
            pause(mode='page')
