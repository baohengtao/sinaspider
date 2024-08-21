import re
import warnings
from copy import deepcopy

import bs4
import pendulum
from bs4 import BeautifulSoup

from sinaspider import console
from sinaspider.helper import encode_wb_id, parse_loc_src

from .helper import WeiboHist


async def parse_weibo_from_web(weibo_info: dict, hist_mblogs=None):
    info = deepcopy(weibo_info)
    assert 'web' in info['mblog_from']
    if (pic_num := info['pic_num']) < len(info['pic_ids']):
        console.log(
            f"pic_num < len(pic_ids) for {info['id']}",
            style="warning")
    else:
        assert pic_num == len(info['pic_ids'])

    user = info.pop('user')
    created_at = pendulum.from_format(
        info.pop('created_at'), 'ddd MMM DD HH:mm:ss ZZ YYYY')
    assert created_at.is_local()
    if region_name := info.pop('region_name', None):
        region_name = region_name.removeprefix('发布于').strip()
    assert 'retweeted_status' not in info
    pics = vids = None
    if pics := info.pop('pics', []):
        if isinstance(pics, dict):
            assert pics.pop('') == {
                'videoSrc': 'https://video.weibo.com/media/play?'
                'livephoto=https%3A%2F%2Flivephoto.us.sinaimg.cn%2F.mov',
                'type': 'livephotos'}
            pics = [pics[str(i)] for i in range(len(pics))]
        assert isinstance(pics, list)
        pics = [pic for pic in pics if 'pid' in pic]
        vids = [p for p in pics if p.get('type') == 'video']
        pics = [p for p in pics if p.get('type') != 'video']
        assert [pic['pid'] for pic in pics] == info.pop('pic_ids')
        pics = [[pic['large']['url'], pic.get('videoSrc', '')]
                for pic in pics]
        vids = [[vid['large']['url'], vid.get('videoSrc', '')] for vid in vids]
        for p in pics:
            if p[0].endswith('.gif'):
                p[1] = ''
            else:
                p[1] = p[1].replace(
                    "livephoto.us.sinaimg.cn", "us.sinaimg.cn")
        pics = ["🎀".join(p).strip("🎀") for p in pics]
    else:
        assert info['pic_num'] == 0

    weibo = dict(
        id=(id_ := int(info.pop('id'))),
        bid=(bid := encode_wb_id(id_)),
        user_id=(user_id := user['id']),
        username=user.get('remark') or user['screen_name'],
        created_at=created_at,
        region_name=region_name,
        photos=pics,
        videos=vids,
        video_url=_get_video_info(info),
        url=f'https://weibo.com/{user_id}/{bid}',
        url_m=f'https://m.weibo.cn/detail/{bid}',
        source=BeautifulSoup(
            info.pop('source').strip(), 'html.parser').text,
        pic_num=info.pop('pic_num'),
        mblog_from=info.pop('mblog_from'),
        edit_count=info.pop('edit_count', 0),
        update_status='updated',

    )

    weibo |= await text_info(info['text'])
    if hist_mblogs:
        weibo = WeiboHist(weibo, hist_mblogs).parse()

    for key in ['reposts_count', 'comments_count', 'attitudes_count']:
        if (v := info.pop(key)) == '100万+':
            v = 1000000
        weibo[key] = v
    weibo = {k: v for k, v in weibo.items() if v not in ['', [], None]}
    weibo['has_media'] = bool(weibo.get('video_url') or weibo.get(
        'photos') or weibo.get('photos_edited'))

    if loc := weibo.get('location'):
        text = weibo.get('text', '').removesuffix('📍')
        assert not text.endswith('📍')
        text += f' 📍{loc}'
        weibo['text'] = text.strip()
    return weibo


def _get_video_info(info) -> str | None:
    page_info = info.get('page_info', {})
    if page_info.get('type') != "video":
        return
    if (urls := page_info['urls']) is None:
        console.log('cannot get video url', style='error')
        return
    for key in ['mp4_1080p_mp4', 'mp4_720p_mp4',
                'mp4_hd_mp4', 'mp4_sd_mp4', 'mp4_ld_mp4']:
        if video_url := urls.get(key):
            return video_url
    console.log(f'no video info:==>{page_info}', style='error')
    raise ValueError('no video info')


async def text_info(text) -> dict:
    hypertext = text.replace('\u200b', '').strip()
    topics = []
    at_users = []
    location_collector = []
    with warnings.catch_warnings(
        action='ignore',
        category=bs4.MarkupResemblesLocatorWarning
    ):
        soup = BeautifulSoup(hypertext, 'html.parser')
    for child in list(soup.contents):
        if child.name != 'a':
            continue
        if m := re.match('^#(.*)#$', child.text):
            topics.append(m.group(1))
        elif child.text[0] == '@':
            user = child.text[1:]
            assert child.attrs['href'][3:] == user
            at_users.append(user)
        elif len(child) == 2:
            url_icon, surl_text = child.contents
            if not url_icon.attrs['class'] == ['url-icon']:
                continue
            _icn = 'timeline_card_small_location_default.png'
            _icn_video = 'timeline_card_small_video_default.png'
            if _icn in url_icon.img.attrs['src']:

                assert surl_text.attrs['class'] == ['surl-text']
                if ((loc := [surl_text.text, child.attrs['href']])
                        not in location_collector):
                    location_collector.append(loc)
                child.decompose()
            elif _icn_video in url_icon.img.attrs['src']:
                child.decompose()
    location, location_id = None, None
    if location_collector:
        if len(location_collector) > 1:
            console.log(
                f'multi location found: {location_collector}', style='warning')
        location, href = location_collector[-1]
        pattern1 = r'^http://weibo\.(?:com|cn)/p/100101([\w\.\_-]+)$'
        pattern2 = (r'^https://m\.weibo\.cn/p/index\?containerid='
                    r'2306570042(\w+)')
        if match := (re.match(pattern1, href)
                     or re.match(pattern2, href)):
            location_id = match.group(1)
        elif 'poixy?lng' in href:
            location = None
            console.log(
                f'location href is not parsed: {href}', style='warning')
        else:
            location_id = await parse_loc_src(href)
    res = {
        'at_users': at_users,
        'topics': topics,
        'location': location,
        'location_id': location_id,
    }
    text = soup.get_text(' ', strip=True).removesuffix('网页链接').strip()
    res['text'] = text
    return {k: v for k, v in res.items() if v is not None}
