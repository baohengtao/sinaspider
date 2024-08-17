import re
from copy import deepcopy

import pendulum
from bs4 import BeautifulSoup

from sinaspider import console
from sinaspider.helper import encode_wb_id

from .helper import (
    WeiboHist,
    get_location_from_mblog,
    get_location_url_from_mblog,
    get_photos_info
)


def parse_weibo_from_weico(mblog: dict, hist_mblogs=None) -> dict:
    info = deepcopy(mblog)
    assert 'weico' in info['mblog_from']
    assert 'retweeted_status' not in info
    assert info.pop('idstr') == info.pop('mid') == str(info['id'])

    if (pic_num := info['pic_num']) < len(info['pic_ids']):
        console.log(
            f"pic_num < len(pic_ids) for {info['id']}",
            style="warning")
    else:
        assert pic_num == len(info['pic_ids'])

    assert info['isLongText'] == (
        ('longText' in info) or (info['pic_num'] > 9))
    if 'longText' in info:
        info['text'] = info['longText']['content']
    url_pattern = r'http://t\.cn/[A-Za-z0-9]+|\u200b'
    text = re.sub(url_pattern, '', info.pop('text'))

    user = info.pop('user')
    created_at = pendulum.from_format(
        info.pop('created_at'), 'ddd MMM DD HH:mm:ss ZZ YYYY')
    assert created_at.is_local()
    if region_name := info.pop('region_name', None):
        region_name = region_name.removeprefix('发布于').strip()
    source = BeautifulSoup(
        info.pop('source'), 'lxml').text.strip()
    assert source != '生日动态'
    pics = get_photos_info(info)
    weibo = dict(
        id=(id_ := int(info.pop('id'))),
        bid=(bid := encode_wb_id(id_)),
        user_id=(user_id := user['id']),
        username=user.get('remark') or user['screen_name'],
        created_at=created_at,
        text=text.strip(),
        region_name=region_name,
        photos=pics,
        url=f'https://weibo.com/{user_id}/{bid}',
        url_m=f'https://m.weibo.cn/detail/{bid}',
        source=source,
        pic_num=pic_num,
        mblog_from=info.pop('mblog_from'),
        edit_count=info.pop('edit_count', 0),

    )
    l1 = get_location_from_mblog(info, from_hist=False)
    l2 = get_location_url_from_mblog(info)
    assert not (l1 and l2)
    if location_info := (l1 or l2):
        weibo |= location_info

    if topic_struct := info.pop('topic_struct', None):
        weibo['topics'] = [topic['topic_title'] for topic in topic_struct]

    if video_info := _get_video_info(info):
        weibo |= video_info

    for key in ['reposts_count', 'comments_count', 'attitudes_count']:
        if (v := info.pop(key)) == '100万+':
            v = 1000000
        weibo[key] = v
    weibo = {k: v for k, v in weibo.items() if v not in ['', [], None]}

    if hist_mblogs:
        weibo = WeiboHist(weibo, hist_mblogs).parse()

    return weibo


def _get_video_info(info):
    video = {}
    if not (page_info := info.pop('page_info', None)):
        return
    if (object_type := page_info.get('object_type')) == 'video':
        media_info = page_info.pop('media_info')
        assert media_info.pop('format') == 'mp4'
        keys = ['mp4_1080p_mp4', 'mp4_1080p_url',
                'mp4_720p_mp4', 'mp4_720p_url',
                'mp4_hd_mp4', 'mp4_hd_url',
                'mp4_sd_mp4', 'mp4_sd_url',
                'mp4_ld_mp4', 'mp4_ld_url']
        for key in keys:
            if url := media_info.get(key):
                video['video_url'] = url
                break
        else:
            console.log(f'no video info:==>{page_info}', style='error')
            raise ValueError('no video info')
        video['video_duration'] = media_info['duration']
    elif object_type == 'story':
        slide = page_info['slide_cover']
        if 'slide_videos' not in slide:
            return
        slide = slide['slide_videos'][0]
        video['video_url'] = slide['url']
        video['video_duration'] = slide['segment_duration'] // 1000
    if video:
        assert page_info['page_title'].endswith(('微博视频', '秒拍视频'))
    else:
        types = [
            'webpage', 'audio', 'hudongvote',
            'movie', None, 'user']
        assert object_type in types, object_type
        assert not page_info['page_title'].endswith('视频')

    return video
