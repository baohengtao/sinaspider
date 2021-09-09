from datetime import datetime, timedelta
from time import sleep
from typing import Union, Iterator, Optional

import pendulum
from tqdm import trange

from sinaspider.helper import get_url, logger, pause, weibo_api_url
from sinaspider.weibo import Weibo


def get_weibo_pages(containerid: str,
                    retweet: bool = True,
                    start_page: int = 1,
                    end_page=None,
                    since: Union[int, str, datetime] = '1970-01-01',
                    download_dir: Optional[str] = None
                    ) -> Iterator[Weibo]:
    """
    爬取某一 containerid 类型的所有微博

    Args:
        containerid(str): 
            - 获取用户页面的微博: f"107603{user_id}"
            - 获取收藏页面的微博: 230259
        retweet (bool): 是否爬取转发微博
        start_page(int): 指定从哪一页开始爬取, 默认第一页.
        end_page: 终止页面, 默认爬取到最后一页
        since: 若为整数, 从哪天开始爬取, 默认所有时间
        download_dir: 下载目录, 若为空, 则不下载


    Yields:
        Generator[Weibo]: 生成微博实例
    """
    if isinstance(since, int):
        assert since > 0
        since = pendulum.now().subtract(since)
    elif isinstance(since, str):
        since = pendulum.parse(since)
    else:
        since = pendulum.instance(since)
    page = max(start_page, 1)
    while True:
        url = weibo_api_url.copy()
        url.args = {'containerid': containerid, 'page': page}
        response = get_url(url)
        js = response.json()
        if not js['ok']:
            if js['msg'] == '请求过于频繁，歇歇吧':
                logger.critical('be banned')
                return js
            else:
                logger.warning(
                    f"not js['ok'], seems reached end, no wb return for page {page}")
                break

        mblogs = [w['mblog']
                  for w in js['data']['cards'] if w['card_type'] == 9]

        for weibo_info in mblogs:
            if weibo_info.get('retweeted_status') and not retweet:
                logger.info('过滤转发微博...')
                continue
            from sinaspider.parser import parse_weibo
            weibo = parse_weibo(weibo_info)
            if not weibo:
                continue
            if weibo['created_at'] < since:
                if weibo['is_pinned']:
                    logger.warning("发现置顶微博, 跳过...")
                    continue
                else:
                    logger.info(
                        f"时间{weibo['created_at']} 在 {since:%y-%m-%d}之前, 获取完毕")
                    end_page = page
                    break

            if download_dir:
                weibo.save_media(download_dir)
            yield weibo

        logger.success(f"++++++++ 页面 {page} 获取完毕 ++++++++++\n")
        page += 1
        if end_page and page > end_page:
            break
        pause(mode='page')


def get_follow_pages(containerid: Union[str, int], cache_days=30) -> Iterator[dict]:
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
                logger.success("关注信息已更新完毕")
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
        if not response.from_cache and js['ok']:
            logger.success(f'页面 {page} 已获取完毕')
        if not response.from_cache:
            pause(mode='page')
        page += 1
