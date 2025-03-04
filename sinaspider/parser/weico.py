import re
from copy import deepcopy

import pendulum
from bs4 import BeautifulSoup

from sinaspider import console
from sinaspider.exceptions import HistError
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
    assert info.pop('idstr') == str(info['id'])

    if (pic_num := info['pic_num']) < len(info['pic_ids']):
        console.log(
            f"pic_num < len(pic_ids) for {info['id']}",
            style="warning")
    else:
        assert pic_num == len(info['pic_ids'])

    if info['isLongText'] != (
            ('longText' in info) or (info['pic_num'] > 9)):
        assert info['isLongText']
        console.log(
            'is long text but longText not in info and pic_num <= 9',
            style='warning')
    if 'longText' in info:
        info['text'] = info['longText']['content']
        info |= info['longText']
        assert info['text'] == info['content']
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
    pics, videos, pic_ids_no_url = get_medias(info)
    if video_url := _get_video_url(info.pop('page_info', None)):
        assert not videos
        videos = [video_url]
    weibo = dict(
        id=(id_ := int(info['id'])),
        bid=(bid := encode_wb_id(id_)),
        user_id=(user_id := user['id']),
        nickname=user['screen_name'],
        username=user.get('remark') or user['screen_name'],
        created_at=created_at,
        text=text.strip(),
        at_users=re.findall(r'@([\u4e00-\u9fa5\w\-\·]+)', text),
        region_name=region_name,
        photos=pics,
        videos=videos,
        pic_ids_no_url=pic_ids_no_url,
        url=f'https://weibo.com/{user_id}/{bid}',
        url_m=f'https://m.weibo.cn/detail/{bid}',
        source=source,
        pic_num=pic_num,
        mblog_from=info.get('mblog_from'),
        edit_count=info.pop('edit_count', 0),
        update_status='updated',
    )
    l1 = get_location_from_mblog(info, from_hist=False)
    l2 = get_location_url_from_mblog(info)
    if l1 and l2:
        if l1 | l2 == l2 | l1:
            l1 |= l2
        else:
            console.log(f'location={l1}, location_url={l2} not same, '
                        f'location_url is ignored', style='error')
    if location_info := (l1 or l2):
        weibo |= location_info

    if topic_struct := info.pop('topic_struct', None):
        weibo['topics'] = sorted(topic['topic_title']
                                 for topic in topic_struct)

    if hist_mblogs:
        weibo = WeiboHist(weibo, hist_mblogs).parse()
    elif pic_ids_no_url:
        raise HistError(weibo)

    for key in ['reposts_count', 'comments_count', 'attitudes_count']:
        if (v := info.pop(key)) == '100万+':
            v = 1000000
        weibo[key] = v
    weibo = {k: v for k, v in weibo.items() if v not in ['', [], None]}
    medias_num = 0
    for k in ['videos', 'photos', 'photos_edited']:
        medias_num += len(weibo.get(k, []))
    weibo['medias_num'] = medias_num

    return weibo


def _get_video_url(page_info) -> str | None:
    video_url = None
    if not page_info:
        return
    if (object_type := page_info.get('object_type')) == 'video':
        media_info = page_info.pop('media_info')
        keys = ['mp4_1080p_mp4', 'mp4_1080p_url',
                'mp4_720p_mp4', 'mp4_720p_url',
                'mp4_hd_mp4', 'mp4_hd_url',
                'mp4_sd_mp4', 'mp4_sd_url',
                'mp4_ld_mp4', 'mp4_ld_url']
        for key in keys:
            if video_url := media_info.get(key):
                break
        fmt = media_info.pop('format')

        if not video_url:
            if h5 := media_info.get('h5_url'):
                console.log(f'ignore video url {h5}', style='error')
            else:
                assert not fmt
            console.log('no video found', style='error')
            return
        else:
            assert fmt in ['mp4', 'm3u8']

    elif object_type == 'story':
        slide = page_info['slide_cover']
        if 'slide_videos' not in slide:
            return
        slide = slide['slide_videos'][0]
        video_url = slide['url']
    elif object_type == 'video_collection':
        console.log('discard video collection', style='error')
        return
    if video_url:
        ends = ('微博视频', '秒拍视频', '微博故事', '美拍')
        if not (title := page_info['page_title']).endswith(ends):
            console.log(f'unknown page_title: {title}', style='error')
        return video_url.replace('http://', 'https://')
    types = [
        'webpage', 'audio', 'book', 'hudongvote', 'cardlist',
        'adFeedEvent', 'article', 'group', 'event',
        'movie', None, 'user', 'wenda', 'live']
    if object_type not in types:
        console.log(f'unknown object_type: {object_type}', style='error')
    assert not page_info['page_title'].endswith('视频')


def get_medias(info):
    info = deepcopy(info)
    assert ('mix_media_info' in info) == ('mix_media_ids' in info)
    if 'mix_media_info' not in info:
        return get_photos_info(info), None, None
    assert 'pic_info' not in info
    media_info = info['mix_media_info']['items']
    vids = [m['data'] for m in media_info if m['type'] == 'video']
    pics = [m['data'] for m in media_info if m['type'] != 'video']
    assert [p['pic_id'] for p in pics] == info['pic_ids'][:len(pics)]
    pic_ids_no_url = info['pic_ids'][len(pics):]
    photos = [[p['largest']['url'], p.get('video', '')] for p in pics]
    videos = [_get_video_url(v) for v in vids]
    for p in photos:
        if p[0].endswith('.gif'):
            if p[1] and ('https://video.weibo.com/media/play?fid=' not in p[1]):
                assert "://g.us.sinaimg.cn/" in p[1]
            p[1] = ''
        else:
            p[1] = p[1].replace("livephoto.us.sinaimg.cn", "us.sinaimg.cn")
    photos = [" ".join(p).strip() for p in photos]

    return photos, videos, (info['pic_ids'] if pic_ids_no_url else None)
