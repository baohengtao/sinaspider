from datetime import datetime, timedelta
from time import sleep
from typing import Generator

import pendulum

from sinaspider.helper import weibo_api_url, get_url, pause
from sinaspider.parser import parse_weibo
from sinaspider import console


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
    page = max(start_page, 1)
    is_continue = True
    while is_continue:
        url = weibo_api_url.copy()
        url.args = {'containerid': containerid, 'page': page}
        response = get_url(url)
        js = response.json()
        if not js['ok']:
            if js['msg'] == '请求过于频繁，歇歇吧':
                console.log('be banned', style='error')
                raise
            else:
                console.log(
                    f"not js['ok'], seems reached end, no wb return for page {page}", style='warning')
                break

        mblogs = [w['mblog']
                  for w in js['data']['cards'] if w['card_type'] == 9]

        for weibo_info in mblogs:
            if not (weibo := parse_weibo(weibo_info)):
                continue
            is_pinned = weibo.pop('is_pinned', None)
            if (created_at := weibo['created_at']) < since:
                if is_pinned:
                    console.log("发现置顶微博, 跳过...")
                    continue
                else:
                    console.log(
                        f"时间{created_at:%y-%m-%d} 在 {since:%y-%m-%d}之前, 获取完毕")
                    is_continue = False
                    break
            yield weibo
        else:
            console.log(f"++++++++ 页面 {page} 获取完毕 ++++++++++\n")
            page += 1
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
            console.log(f'页面 {page} 已获取完毕')
        if not response.from_cache:
            pause(mode='page')
        page += 1
