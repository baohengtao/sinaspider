import json
import re
from itertools import chain
from typing import Optional
from typing import Union

import pendulum
from bs4 import BeautifulSoup
from pendulum.parsing import ParserError

from sinaspider import console
from sinaspider.helper import get_url, pause, weibo_api_url, normalize_str
print = console.print

def get_weibo_by_id(wb_id) -> Optional[dict]:
    if weibo_info := _get_weibo_info_by_id(wb_id):
        return parse_weibo(weibo_info)


def parse_weibo(weibo_info: dict) -> dict:
    """
    对从网页爬取到的微博进行解析.
    若为转发微博:
        若原微博已删除, 返回 None;
        若原微博为长微博, 则爬取原微博并解析
    若为原创微博, 则直接解析
    Args:
        weibo_info (dict): 原始微博信息
    Returns:
        解析后的微博信息.
    """
    weibo = _parse_weibo_card(weibo_info)
    if weibo_info['pic_num'] > 9:
        weibo_info |= _get_weibo_info_by_id(weibo_info['id'])
        weibo = _parse_weibo_card(weibo_info)
    return weibo


def _get_weibo_info_by_id(wb_id: Union[int, str]) -> dict:
    """
    爬取指定id的微博, 若原微博已删除, 返回None

    Args:
        wb_id (Union[int, str]): 微博id

    Returns:
        Weibo instance if exists, else None

    """
    url = f'https://m.weibo.cn/detail/{wb_id}'
    response = get_url(url, expire_after=-1)
    html = response.text
    html = html[html.find('"status"'):]
    html = html[:html.rfind('"hotScheme"')]
    html = html[:html.rfind(',')]
    weibo_info = {}
    if html:
        html = f'{{{html}}}'
        weibo_info = json.loads(html, strict=False)['status']
        if not weibo_info:
            response.revalidate(3600 * 24 * 30)
            console.log(f'{url} cannot load', style='warning')
        else:
            console.log(f'{wb_id} fetched')
    if response.from_cache:
        console.log(f'fetching {wb_id} from cache')
    else:
        console.log('pausing...')
        pause(mode='page')
    return weibo_info


def _parse_weibo_card(weibo_card: dict) -> dict:
    class _WeiboCardParser:
        """用于解析原始微博内容"""

        def __init__(self):
            self.card = weibo_card
            self.wb = {}
            self.parse_card()

        def parse_card(self):
            self.basic_info()
            self.photos_info()
            self.video_info()
            try:
                self.wb |= text_info(self.card['text'])
            except AssertionError:
                console.print_exception(show_locals=True)
                raise
            # self.retweet_info()
            self.wb = {k: v for k, v in self.wb.items() if v or v == 0}

#         def retweet_info(self):
#             if original := self.card.get('retweeted_status'):
#                 self.wb.update(
#                     original_id=original['id'],
#                     original_bid=original['bid'],
#                     original_uid=original['user']['id'],
#                     original_text=text_info(original['text']).get('text')
#                 )

        def basic_info(self):
            user = self.card['user']
            created_at = pendulum.parse(self.card['created_at'], strict=False)
            assert created_at.is_local()
            self.wb.update(
                user_id=(user_id := user['id']),
                screen_name=user.get('remark') or user['screen_name'],
                id=(id := int(self.card['id'])),
                bid=(bid := self.card['bid']),
                url=f'https://weibo.com/{user_id}/{bid}',
                url_m=f'https://m.weibo.cn/detail/{id}',
                created_at=created_at,
                source=self.card['source'],
            )
            if pin := self.card.get('title'):
                self.wb['is_pinned'] = (pin.get('text') == '置顶')
            for key in ['reposts_count', 'comments_count', 'attitudes_count']:
                if (v := self.card[key]) == '100万+':
                    v = 1000000
                self.wb[key] = v

        def photos_info(self):
            pics = self.card.get('pics', [])
            pics = [p['large']['url'] for p in pics]
            live_photo = {}
            live_photo_prefix = 'https://video.weibo.com/media/play?livephoto=//us.sinaimg.cn/'
            if pic_video := self.card.get('pic_video'):
                live_photo = {}
                for p in pic_video.split(','):
                    sn, path = p.split(':')
                    live_photo[int(sn)] = f'{live_photo_prefix}{path}.mov'
                assert max(live_photo) < len(pics)
            self.wb['photos'] = {str(i + 1): [pic, live_photo.get(i)]
                                 for i, pic in enumerate(pics)}

        def video_info(self):
            page_info = self.card.get('page_info', {})
            if not page_info.get('type') == "video":
                return
            media_info = page_info['urls'] or page_info['media_info']
            keys = [
                'mp4_1080p_mp4', 'mp4_720p', 'mp4_720p_mp4', 'mp4_hd_mp4', 'mp4_hd', 'mp4_hd_url',
                'hevc_mp4_hd', 'mp4_ld_mp4', 'mp4_ld', 'hevc_mp4_ld', 'stream_url_hd', 'stream_url',
                'inch_4_mp4_hd', 'inch_5_mp4_hd', 'inch_5_5_mp4_hd', 'duration'
            ]
            if not set(media_info).issubset(keys):
                console.log(media_info)
                console.log(str(set(media_info) - set(keys)), style='error')
                # assert False
            urls = [v for k in keys if (v := media_info.get(k))]
            if not urls:
                console.log(f'no video info:==>{page_info}', style='warning')
            else:
                self.wb['video_url'] = urls[0]
                if duration := float(media_info.get('duration', 0)):
                    self.wb['video_duration'] = duration

    def text_info(text):
        if not text.strip():
            return {}
        at_list, topics_list = [], []
        soup = BeautifulSoup(text, 'html.parser')

        for a in soup.find_all('a'):
            at_sign, user = a.text[0], a.text[1:]
            if at_sign == '@':
                assert a.attrs['href'][3:] == user
                at_list.append(user)

        for topic in soup.find_all('span', class_='surl-text'):
            if m := re.match('^#(.*)#$', topic.text):
                topics_list.append(m.group(1))

        location = ''

        for url_icon in soup.find_all('span', class_='url-icon'):
            location_icon = 'timeline_card_small_location_default.png'
            if location_icon in url_icon.find('img').attrs['src']:
                location_span = url_icon.findNext('span')
                assert location_span.attrs['class'] == ['surl-text']
                location = location_span.text
        return {
            'text': soup.text,
            'at_users': at_list,
            'topics': topics_list,
            'location': location
        }

    return _WeiboCardParser().wb


def get_user_by_id(uid: int, cache_days=30):
    expire_after = cache_days * 24 * 3600
    url = weibo_api_url.copy()

    # 获取来自m.weibo.com的信息
    url.args = {'containerid': f"230283{uid}_-_INFO"}
    respond_card = get_url(url, expire_after)
    user_card = _parse_user_card(respond_card)

    # 获取主信息
    url.args = {'containerid': f"100505{uid}"}
    respond_info = get_url(url, expire_after)
    js = json.loads(respond_info.content)
    while True:
        try:
            user_info = js['data']['userInfo']
            user_info.pop('toolbar_menus', '')
            break
        except KeyError:
            print(js, url)
            pause(mode='user')
            get_user_by_id(uid, cache_days=0)

    # 获取来自cn的信息
    respond_cn = get_url(f'https://weibo.cn/{uid}/info', expire_after)
    user_cn = _parse_user_cn(respond_cn)

    # 合并信息
    user = user_card | user_cn | user_info
    s = {(k, str(v)) for k, v in chain.from_iterable(
        [user_card.items(), user_cn.items(), user_info.items()])}
    if emp := {(k, str(v)) for k, v in user.items()} - s:
        console.log(emp, style='error')
    try:
        user = _user_info_fix(user)
    except (KeyError, AssertionError) as e:
        print(user)
        raise e
    user['info_updated_at'] = pendulum.now()
    from_cache = [r.from_cache for r in [
        respond_card, respond_cn, respond_info]]
    # assert min(from_cache) is max(from_cache)
    if not all(from_cache):
        console.log(f"{user['screen_name']} 信息已从网络获取.")
        pause(mode='page')
    return user


def _user_info_fix(user_info: dict) -> dict:
    """清洗用户信息."""
    user_info = user_info.copy()
    if '昵称' in user_info:
        assert user_info.get('screen_name', '') == user_info.pop('昵称', '')
    user_info['screen_name'] = user_info['screen_name'].replace('-', '_')

    if '简介' in user_info:
        u1, u2 = user_info.get('description', '').strip(), user_info.pop(
            '简介', '').replace('暂无简介', '').strip()
        if u1 != u2:
            console.log([u1, u2], style='error')
    if 'Tap to set alias' in user_info:
        assert user_info.get('remark', '') == user_info.pop(
            'Tap to set alias', '')
    if user_info.get('gender') == 'f':
        assert user_info.pop('性别', '女') == '女'
        user_info['gender'] = 'female'
    elif user_info.get('gender') == 'm':
        assert user_info.pop('性别', '男') == '男'
        user_info['gender'] = 'male'

    if 'followers_count_str' in user_info:
        assert user_info.pop('followers_count_str') == str(user_info['followers_count'])

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
    values = [user_info.pop(k, '').strip() for k in keys]
    values = [v for v in values if v]
    if values:
        if not len(set(values)) == 1:
            console.log(set(values), style='error')
        user_info[keys[0]] = values[0]

    if '生日' in user_info:
        assert 'birthday' not in user_info or user_info['birthday'] == user_info['生日']
        user_info['birthday'] = user_info.pop('生日')
    if birthday := user_info.get('birthday', '').strip():
        birthday = birthday.split()[0].strip()
        if birthday == '0001-00-00':
            pass
        elif re.match(r'\d{4}-\d{2}-\d{2}', birthday):
            try:
                age = pendulum.parse(birthday).diff().years
                user_info['age'] = age
            except ParserError:
                console.log(f'Cannot parse birthday {birthday}', style='error')
            user_info['birthday'] = birthday
    if education := user_info.pop('学习经历', ''):
        assert 'education' not in user_info
        for key in ['大学', '海外', '高中', '初中', '中专技校', '小学']:
            assert user_info.pop(key, '') in ' '.join(education)
        user_info['education'] = education

    user_info['homepage'] = f'https://weibo.com/u/{user_info["id"]}'
    user_info = {k: v for k, v in user_info.items() if v or v == 0}
    user_info['hometown'] = user_info.pop('家乡', '')
    user_info = {k: normalize_str(v) for k, v in user_info.items()}

    return user_info


def _parse_user_cn(respond):
    """解析weibo.cn的内容"""
    soup = BeautifulSoup(respond.text, 'lxml')
    divs = soup.find_all('div')
    info = dict()
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
                            info[key] = value
                        except ValueError as e:
                            console.log(f'{text} cannot parsed', style='error')
                            raise e

            elif tip.text == '学习经历' or '工作经历':
                education = c.text.replace('\xa0', ' ').split('·')
                info[tip.text] = [e.strip() for e in education if e]
            else:
                info[tip.text] = c.text.replace('\xa0', ' ')

    if info.get('生日') == '01-01':
        info.pop('生日')
    return info


def _parse_user_card(respond_card):
    user_card = respond_card.json()['data']['cards']
    user_card = sum([c['card_group'] for c in user_card], [])
    user_card = {card['item_name']: card['item_content']
                 for card in user_card if 'item_name' in card}
    if user_card.get('生日', '').strip():
        user_card['生日'] = user_card['生日'].split()[0]
    return user_card
