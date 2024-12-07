import asyncio
import itertools
import re
from pathlib import Path
from typing import AsyncIterator, Self

import pendulum
from bs4 import BeautifulSoup

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.helper import fetcher


class SinaBot:
    @classmethod
    async def create(cls, art_login: bool = True) -> Self:
        bot = cls(art_login)
        screen_name = await fetcher.login(bot.art_login)
        console.log(
            f'init bot logined as {screen_name} (art_login: {art_login})')
        return bot

    def __init__(self, art_login: bool = True) -> None:
        self.art_login = art_login

    async def set_remark(self, uid: int, remark: str):
        s = '0726b708' if self.art_login else 'c773e7e0'
        url = "https://api.weibo.cn/2/friendships/remark/update"
        data = {
            "uid": uid,
            "remark": remark.strip(),
            "c": "weicoabroad",
            "s": s,
        }
        response = await fetcher.post(url, data=data, art_login=self.art_login)
        response.raise_for_status()
        js = response.json()
        if js.get('errormsg'):
            raise ValueError(js)

    async def set_special_follow(self, uid, special_follow: bool):
        s = "4fff7801"  # for art_login
        cmd = 'create' if special_follow else 'destroy'
        url = (f"https://api.weibo.cn/2/friendships/special_attention_{cmd}?"
               f"from=10DA199020&c=iphone&s={s}&uid={uid}"
               )
        js = await fetcher.get_json(url, art_login=self.art_login)
        if js.get('errmsg') == 'not followed':
            console.log(
                f'https://m.weibo.cn/u/{uid} not followed, '
                'adding to special following failed', style='error')
            return
        assert js['result'] is True
        # url = ('https://m.weibo.cn/api/container/getIndex?'
        #        f'containerid=100505{uid}')
        # js = fetcher.get(url, art_login=self.art_login).json()
        # user_info = js['data']['userInfo']
        # assert user_info['special_follow'] is True

    async def follow(self, uid):
        url = "https://api.weibo.cn/2/friendships/create"
        data = {
            "c": "weicoabroad",
            "from": "12CC293010",
            "s": "99312000",
            "uid": uid
        }
        r = fetcher.post(url, data=data, art_login=self.art_login)
        r.raise_for_status()
        js = r.json()
        if (errmsg := js.get('errmsg')) == '该用户不存在':
            console.log(f'{errmsg} (https://weibo.com/u/{uid})')
            return
        elif errmsg:
            raise ValueError(js)
        url = ('https://m.weibo.cn/api/container/getIndex?'
               f'containerid=100505{uid}')
        js = await fetcher.get_json(url, art_login=self.art_login)
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
        response = fetcher.post(url,  data=data, art_login=self.art_login)
        response.raise_for_status()
        js = response.json()
        if js.get('errmsg') == 'not followed':
            console.log(f'{uid} alread unfollowed', )
        else:
            assert js['following'] is False
            console.log(
                f'{js["screen_name"]} (https://weibo.com/u/{uid}) unfollowed')

    async def get_following_list(
            self, pages=None,
            max_user=None,
            special_following=False) -> AsyncIterator[dict]:
        s = '0726b708' if self.art_login else 'c773e7e0'
        if special_following:
            gid = '4955723680713860' if self.art_login else '4268552720689336'
            containerid = f'231093_-_selfgroupfollow_-_{gid}'
        else:
            containerid = '231093_-_selffollowed'
        url = ('https://api.weibo.cn/2/cardlist?c=weicoabroad'
               f'&containerid={containerid}&page=%s&s={s}')
        cnt = 0
        if pages is None:
            pages = itertools.count(start=1)
        for page in pages:
            js = await fetcher.get_json(url % page, art_login=self.art_login)
            if (cards := js['cards']) is None:
                return
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
                if card['card_type'] == 58:
                    assert card == cards[0]
                    continue
                assert card['card_type'] == 10
                user = card['user']
                user = {k: user[k] for k in keys}
                yield user
                cnt += 1
            if max_user and cnt >= max_user:
                break

    async def get_friends_list(self):
        s = 'c773e7e0'  # if self.art_login is False
        url = ('https://api.weibo.cn/2/friendships/bilateral?c=weicoabroad'
               f'&real_relationships=1&s={s}&trim_status=1&page=%s')
        cnt = 0
        for page in itertools.count(start=1):
            js = await fetcher.get_json(url % page, art_login=self.art_login)
            if not (users := js['users']):
                console.log(f'{cnt} friends fetched')
                break
            console.log(f'{len(users)} users find on page {page}')
            keys = ['id', 'screen_name', 'remark']
            for user in users:
                yield {k: user[k] for k in keys}
                cnt += 1

    async def get_timeline(self, download_dir: Path,
                           since: pendulum.DateTime,
                           friend_circle=False):
        from sinaspider.model import UserConfig, Weibo
        await fetcher.toggle_art(self.art_login)
        async for status in Page.timeline(
                since=since, friend_circle=friend_circle):
            uid = status['user']['id']
            if not (config := UserConfig.get_or_none(user_id=uid)):
                continue
            config: UserConfig
            if not (config.weibo_fetch and config.weibo_fetch_at):
                continue
            created_at = pendulum.from_format(
                status['created_at'], 'ddd MMM DD HH:mm:ss ZZ YYYY')
            if created_at <= config.weibo_fetch_at:
                assert Weibo.get_or_none(id=status['id'])
                continue
            for _ in range(3):
                config = await UserConfig.from_id(uid)
                if config.following == self.art_login:
                    await config.fetch_weibo(download_dir)
                    break
            else:
                raise ValueError(f'{config.username} not following')
            if config.liked_next_fetch:
                console.log(
                    f'latest liked fetch at {config.liked_fetch_at:%y-%m-%d}, '
                    f'next fetching time is {config.liked_next_fetch:%y-%m-%d}')
                # if pendulum.now() > config.liked_next_fetch:
                #     config.fetch_liked(download_dir)


class Page:
    def __init__(self, user_id: int) -> None:
        self.id = int(user_id)

    async def homepage_web(self) -> AsyncIterator[dict]:
        """
        Fetch user's homepage weibo.

        Args:
                start_page: the start page to fetch
                parse: whether to parse weibo, default True
        """
        url = ('https://m.weibo.cn/api/container/getIndex?containerid='
               f'230413{self.id}_-_WEIBO_SECOND_PROFILE_ORI')
        since_id = None
        ids = []
        for page in itertools.count(start=1):
            params = {'since_id': since_id} if since_id else None
            data = (await fetcher.get_json(url, params=params))['data']
            created_at = None

            for weibo_info in _yield_from_cards(data['cards']):
                if weibo_info['source'] == '生日动态':
                    continue
                if weibo_info['user']['id'] != self.id:
                    assert '评论过的微博' in weibo_info['title']['text']
                    continue
                if 'retweeted_status' in weibo_info:
                    continue
                weibo_info['is_pinned'] = weibo_info.get(
                    'title', {}).get('text') == '置顶'
                weibo_info['mblog_from'] = 'timeline_web'
                assert weibo_info['id'] not in ids
                ids.append(weibo_info['id'])
                created_at = pendulum.from_format(
                    weibo_info['created_at'], 'ddd MMM DD HH:mm:ss ZZ YYYY')
                yield weibo_info
            else:
                msg = f'页面 {page} 获取完毕'
                if created_at:
                    msg += ' ' + created_at.format('YYYY-MM-DD HH:mm:ss')
                console.log(f"++++++++ {msg} ++++++++\n")
            if not (since_id := data['cardlistInfo'].get('since_id')):
                console.log(
                    f"seems reached end at page {page} for {url, params}",
                    style='warning'
                )
                return

    async def homepage_weico(self, start_page: int = 1) -> AsyncIterator[dict]:
        """
        Fetch user's homepage weibo.

        Args:
                start_page: the start page to fetch
        """

        for page in itertools.count(start=max(start_page, 1)):
            created_at = None
            async for weibo_info in self._get_single_page_weico(page):
                if weibo_info is None:
                    return
                created_at = pendulum.from_format(
                    weibo_info['created_at'], 'ddd MMM DD HH:mm:ss ZZ YYYY')
                yield weibo_info
            msg = f'页面 {page} 获取完毕'
            if created_at:
                msg += ' ' + created_at.format('YYYY-MM-DD HH:mm:ss')
            console.log(
                f"++++++++ 页面 {msg} 获取完毕 ++++++++++\n")

    async def _get_single_page_weico(self, page: int) -> AsyncIterator[dict]:

        s = "88888888" if fetcher.art_login else "33333333"
        url = ('https://api.weibo.cn/2/profile/statuses/tab?c=weicoabroad&'
               f'containerid=230413{self.id}_-_WEIBO_SECOND_PROFILE_WEIBO&'
               f'from=12DC193010&page=%s&s={s}'
               )
        cards = (await fetcher.get_json(url % page))['cards']
        mblogs = list(_yield_from_cards(cards))
        if not mblogs:
            if len(cards) == 2:
                assert cards[0]['card_group'][0]['desc'] == '发布微博'
                console.log('seems fetching weibos of self', style='error')
            else:
                assert len(cards) == 1
            assert cards[-1]['name'] == '暂无微博'
            console.log(
                f"seems reached end at page {page} for {url % page}",
                style='warning'
            )
            yield None

        for weibo_info in mblogs:
            weibo_info['source'] = BeautifulSoup(
                weibo_info['source'], 'lxml').text.strip()
            if weibo_info['source'] in ['生日动态', '会员特权专用']:
                continue
            if weibo_info['user']['id'] != self.id:
                assert (
                    (weibo_info.get('ori_uid') == self.id)
                    or weibo_info.get('like_status')
                    or weibo_info.get('comment_status')
                    or re.findall(r'(评论|赞)过的微博',
                                  weibo_info['title']['text']))
                continue
            if 'retweeted_status' in weibo_info:
                continue
            weibo_info['is_pinned'] = weibo_info.get(
                'title', {}).get('text') == '置顶'
            weibo_info['mblog_from'] = 'timeline_weico'
            yield weibo_info

    @staticmethod
    async def timeline(since: pendulum.DateTime, friend_circle=False):
        """Get status on my timeline."""
        next_cursor = None
        # seed = 'https://m.weibo.cn/feed/friends'
        s = "99312000" if fetcher.art_login else "b59fafff"
        if friend_circle:
            seed = ("https://api.weibo.cn/2/groups/timeline?"
                    "&c=weicoabroad&from=12CC293010"
                    "&list_id=100096619193364"
                    f"&s={s}"
                    )
        else:
            seed = ('https://api.weibo.cn/2/statuses/friends_timeline?'
                    f'feature=1&c=weicoabroad&from=12CC293010&i=f185221&s={s}')
        while True:
            url = f'{seed}&max_id={next_cursor}' if next_cursor else seed
            data = await fetcher.get_json(url)
            next_cursor = data['next_cursor']
            created_at = None
            for status in data['statuses']:
                if 'retweeted_status' in status:
                    assert friend_circle
                    continue
                source = BeautifulSoup(status['source'], 'lxml').text.strip()
                if source in ['生日动态', '会员特权专用']:
                    continue
                created_at = pendulum.from_format(
                    status['created_at'], 'ddd MMM DD HH:mm:ss ZZ YYYY')
                if created_at < since:
                    console.log(
                        f'🎉 created_at:{created_at: %y-%m-%d} '
                        f'< since:{since: %y-%m-%d}, finished')
                    return
                for key in ['pic_num', 'mix_media_ids', 'page_info']:
                    if status.get(key):
                        yield status
                        break

            console.log(f'created_at:{created_at}')

    async def _liked_card(self) -> AsyncIterator[dict]:
        if fetcher.art_login is None:
            await fetcher.toggle_art(True)
        s = '0726b708' if fetcher.art_login else 'c773e7e0'
        url = ('https://api.weibo.cn/2/cardlist?c=weicoabroad&containerid='
               f'230869{self.id}-_mix-_like-pic&page=%s&s={s}')
        for page in itertools.count(start=1):
            console.log(f'Fetching liked weibo page {page}...')
            while True:
                if (r := await fetcher.get(url % page)).status_code != 200:
                    console.log(
                        f'{r.url} get status code {r.status_code}...',
                        style='warning')
                elif 'cards' in (js := r.json()):
                    break
                elif js.get('errmsg') == 'attitude: user status wrong':
                    raise UserNotFoundError(
                        f'attitude: user {self.id} status wrong')
                else:
                    console.log(f'{r.url} get js error: {js}', style='error')
                console.log('sleeping 60 seconds')
                await asyncio.sleep(60)

            if (cards := js['cards']) is None:
                console.log(
                    f"js[cards] is None for [link={r.url}]r.url[/link]",
                    style='warning')
                break
            for mblog in _yield_from_cards(cards):
                yield mblog

    async def liked(self) -> AsyncIterator[dict]:
        ids = []
        async for weibo_info in self._liked_card():
            if 'retweeted_status' in weibo_info:
                continue
            if weibo_info.get('deleted') == '1':
                continue
            if weibo_info['pic_num'] == 0:
                continue
            if weibo_info['user']['gender'] == 'm':
                continue
            weibo_info['mblog_from'] = 'liked_weico'
            if weibo_info['id'] in ids:
                continue
            ids.append(weibo_info['id'])

            yield weibo_info

    async def friends(self, parse=True):
        """Get user's friends."""
        pattern = (r'(https://tvax?\d\.sinaimg\.cn)/'
                   r'(?:crop\.\d+\.\d+\.\d+\.\d+\.\d+\/)?(.*?)\?.*$')
        friend_count = 0
        if fetcher.art_login is None:
            await fetcher.toggle_art(True)
        s = '0726b708' if fetcher.art_login else 'c773e7e0'
        for page in itertools.count(start=1):
            url = ("https://api.weibo.cn/2/friendships/bilateral?"
                   f"c=weicoabroad&page={page}&s={s}&uid={self.id}")
            js = await fetcher.get_json(url)
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
                    raw['created_at'], 'ddd MMM DD HH:mm:ss ZZ YYYY')
                p1, p2 = re.match(pattern, raw['avatar_hd']).groups()
                info['avatar_hd'] = f'{p1}/large/{p2}'
                yield info if parse else raw
                friend_count += 1

    async def _get_page_post_on(self, page: int):
        from sinaspider.model import WeiboCache
        mblogs = [mblog async for mblog in self._get_single_page_weico(page)]
        while mblogs:
            if (mblog := mblogs.pop()) is None:
                continue
            if mblog.get('title', {}).get('text') == '置顶':
                continue
            cache = await WeiboCache.upsert(mblog)
            info = await cache.parse()
            if info.get('videos'):
                continue
            return info['created_at']

    async def get_visibility(self) -> bool:
        """判断用户是否设置微博半年内可见."""
        start, end = 1, 4
        post_ons = []
        while post_on := await self._get_page_post_on(end):
            post_ons.append(post_on)
            start = end + 1
            if (days := post_on.diff().days) > 360:
                end *= 2
            else:
                end = min(max(end + 3, end * 360 // days), end * 2)
            console.log(f'checking page {(start, end)}...'
                        f'to get visibility (days:{days})')
        else:
            end -= 1

        while start <= end:
            mid = (start + end) // 2
            console.log(f'checking page {mid}...to get visibility')
            if not (post_on := await self._get_page_post_on(mid)):
                end = mid - 1
            else:
                post_ons.append(post_on)
                start = mid + 1
        assert post_ons == sorted(post_ons, reverse=True)
        if post_on := post_ons[-1] if post_ons else None:
            console.log(f'all weibos are after {post_on:%y-%m-%d}',
                        style='error')
        else:
            console.log('no weibo found.', style='error')
        if post_on and post_on < pendulum.now().subtract(months=12):
            return True
        else:
            return False


def _yield_from_cards(cards):
    for card in cards:
        if card['card_type'] == 9:
            yield card['mblog']
        elif card['card_type'] == 11:
            yield from _yield_from_cards(card['card_group'])
