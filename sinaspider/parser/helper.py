
from copy import deepcopy

import pendulum

from sinaspider import console
from sinaspider.exceptions import HistLocationError
from sinaspider.helper import round_loc


class WeiboHist:
    def __init__(self, weibo_dict: dict,
                 hist_mblogs: list[dict]) -> None:
        self.weibo_dict = weibo_dict
        self.hist_mblogs = [
            h for h in hist_mblogs
            if '抱歉，此微博已被删除。' not in h['text']
        ]

    def parse(self) -> dict:
        if edit_at := self.hist_mblogs[-1].get('edit_at'):
            # assert len(self.hist_mblogs) > 1
            edit_at = pendulum.from_format(
                edit_at, 'ddd MMM DD HH:mm:ss ZZ YYYY')
            assert edit_at.is_local()
            assert 'edit_at' not in self.weibo_dict
            self.weibo_dict['edit_at'] = edit_at
        # else:
        #     assert len(self.hist_mblogs) == 1
        self.parse_photos_info()

        location_info = parse_location_info_from_hist(self.hist_mblogs) or {}
        assert self.weibo_dict | location_info == location_info | self.weibo_dict
        self.weibo_dict |= location_info
        try:
            self.weibo_dict = merge_hist_location(self.weibo_dict)
        except (AssertionError, KeyError):
            raise HistLocationError(self.weibo_dict)
        return self.weibo_dict

    def parse_photos_info(self) -> dict:
        final_photos = self.weibo_dict.pop('photos', [])
        photos, ori_num = get_photos_info_from_hist(self.hist_mblogs)

        if not set(final_photos).issubset(set(photos)):
            photos_no_live = {x.split()[0] for x in photos}
            assert set(final_photos).issubset(photos_no_live)

        photos, edited = photos[:ori_num], photos[ori_num:]
        info = dict(photos=photos, photos_edited=edited)
        assert self.weibo_dict | info == info | self.weibo_dict
        self.weibo_dict |= info


def get_photos_info(info: dict) -> list[str]:
    if info['pic_num'] == 0:
        return []
    if pic_infos := info.get('pic_infos'):
        assert list(pic_infos) == info['pic_ids']
        photos = [[p['largest']['url'], p.get('video', '')]
                  for p in pic_infos.values()]
    elif page_info := info.get('page_info'):
        assert info['pic_num'] == 1
        page_pic = page_info['page_pic']
        url = page_pic if isinstance(
            page_pic, str) else page_pic['url']
        photos = [[url, '']]
    else:
        assert info['pic_num'] == 1
        for struct in info['url_struct']:
            if pic_infos := struct.get('pic_infos'):
                break
        info = struct
        assert list(pic_infos) == info['pic_ids']
        photos = [[p['largest']['url'], p.get('video', '')]
                  for p in pic_infos.values()]

    for p in photos:
        if p[0].endswith('.gif'):
            p[1] = ''
        else:
            p[1] = p[1].replace("livephoto.us.sinaimg.cn", "us.sinaimg.cn")
    assert len(photos) == len(info['pic_ids'])
    photos = [' '.join(p).strip() for p in photos]
    return photos


def get_photos_info_from_hist(hist_mblogs) -> tuple[list[str], int]:
    photos, ori_num = [], None
    for mblog in hist_mblogs:
        try:
            ps = get_photos_info(mblog)
        except KeyError:
            if '抱歉，此微博已被删除。查看帮助：' not in mblog['text']:
                console.log(
                    'parse photo info with hist failed for weibo',
                    style='error')
            continue
        if ori_num is None:
            ori_num = len(ps)
        for p in ps:
            if p not in photos:
                photos.append(p)
    assert ori_num is not None
    return photos, ori_num


def get_region_from_mblog(mblog):
    if region_name := mblog.get('region_name'):
        region_name = region_name.removeprefix('发布于').strip()
    if region_name == '其他':
        region_name = None
    return region_name


def get_location_url_from_mblog(mblog):
    url_struct = mblog.get('url_struct', [])
    pos = [u for u in url_struct if u.get('object_type') == 'place']
    if not pos:
        return None
    assert len(pos) == 1
    pos = pos[0]
    page_id = pos['page_id']
    assert page_id.startswith('100101')
    location_id = page_id.removeprefix('100101')
    location = pos['url_title']
    return {
        'location': location,
        'location_id': location_id,
    }


def get_location_from_mblog(mblog, from_hist=True):
    mblog = deepcopy(mblog)
    assert from_hist == (mblog['id'] == -1)

    tag_struct = [s for s in mblog.get(
        'tag_struct', []) if s.get('otype') == 'place']
    assert len(tag_struct) <= 1
    if tag_struct:
        tag_struct = tag_struct[0]
        location_id: str = tag_struct['oid']
        assert location_id.startswith('1022:100101')
        location_id = location_id.removeprefix('1022:100101')
        location = tag_struct['tag_name']
        tag_struct = {
            'location': location,
            'location_id': location_id,
        }
        if mblog_from := mblog.get('mblog_from'):
            assert not from_hist
            if mblog_from != 'liked_weico':
                assert mblog_from in ['timeline_weico', 'page_weico']
                tag_struct['location_title'] = tag_struct.pop('location')
        else:
            assert from_hist

    # parse geo
    if geo := mblog.get('geo'):
        assert geo.pop('type') == 'Point'
        lat, lng = geo.pop('coordinates')
        lat, lng = round_loc(lat, lng)
        assert not geo or not from_hist
        geo = {
            'latitude': lat,
            'longitude': lng,
        }

    # parse annotations
    annotations = [a for a in mblog.get(
        'annotations', []) if 'place' in a]
    if annotations:
        annotations, *rest = annotations
        annotations = annotations['place']
        for a in rest:
            assert annotations == a['place']
        if set(annotations) == {'place'}:
            annotations = annotations['place']
        if annotations == {'spot_type': '0'}:
            annotations = None
        else:
            annotations = {
                'location_title': annotations.get('title'),
                'location_id': annotations['poiid'],
            }

    # merge annotations to tag_struct or geo
    if tag_struct:
        if annotations:
            assert tag_struct['location_id'] == annotations['location_id']
            tag_struct = annotations | tag_struct
    elif geo and annotations:
        geo |= annotations
    else:
        if geo and not annotations:
            console.log(
                f'geo {geo} found but no annotation', style='error')

        return annotations or None

    if tag_struct and geo:
        return tag_struct | geo
    else:
        return geo or tag_struct


def parse_location_info_from_hist(hist_mblogs) -> dict | None:
    if not hist_mblogs:
        return
    regions = [get_region_from_mblog(mblog) for mblog in hist_mblogs]
    locations_from_url = [get_location_url_from_mblog(
        mblog) for mblog in hist_mblogs]
    locations = [get_location_from_mblog(mblog) for mblog in hist_mblogs]
    for i in range(len(hist_mblogs)):
        x, y = locations[i] or {}, locations_from_url[i] or {}
        assert x | y == y | x
        locations[i] = (x | y) or None

    rl = None
    has_geo = False
    for reginon, location in zip(regions, locations):
        if location is None:
            continue
        if rl is None:
            rl = (reginon, location)
        if location.get('latitude'):
            if location.get('location'):
                rl = (reginon, location)
                break
            else:
                has_geo = True

    if rl:
        region, location = rl
        assert not has_geo or 'latitude' in location

        if 'location' not in location:
            assert all('location' not in loc for loc in locations)
            console.log(f'no location found, using title instead: {location}')

    else:
        for region in regions:
            if region:
                break
        location = locations[0]
        assert locations == [None] * len(locations)

    rs = {r for r in regions if r is not None}
    if len(rs) > 1:
        console.log(f'multi region found: {rs},  {region} is chosen')

    ls = {loc['location_id']: loc for loc in locations
          if loc is not None and loc['location_id'] != location['location_id']}
    if ls:
        ls = [" ".join(map(str, loc.values())) for loc in ls.values()]
        console.log(
            'multi location found:\n'
            f'choosen: {" ".join(map(str, location.values()))}\n'
            f'ignored: {ls}')

    return dict(locations=locations, selected_location=location,
                regions=regions, selected_region=region
                )


def merge_hist_location(weibo: dict) -> dict:
    # get regions and location which parsed from history
    regions = weibo.get('regions')
    locations = weibo.get('locations')
    assert bool(regions) == bool(locations)
    if not regions:
        return weibo

    # compare region
    if (x := weibo.get('region_name')) and x != regions[-1]:
        console.log(
            '>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>',
            style='warning')
        console.log('region not match: ')
        console.log(f'regions in hist: {regions}')
        console.log(f'region in weibo: {weibo.get("region_name")}')
        console.log('<'*50, style='warning')

    # compare location
    mblog_from = weibo['mblog_from']
    if not weibo.get('location') and not weibo.get('location_title'):
        if 'weico' in mblog_from:
            x = locations[-1] or {}
            assert not x.get('location') and not x.get('location_title')
    else:
        lx = locations[-1]
        assert weibo['location_id'] == lx['location_id']
        if weibo.get('location') != lx.get('location'):
            assert 'weico' in mblog_from
            x = lx.get('location', '').split('·', maxsplit=1)[-1]
            assert weibo['location_title'] in [lx['location_title'], x]

    weibo['region_name'] = weibo.pop('selected_region')
    if location := weibo.pop('selected_location'):
        weibo |= location
        weibo.pop('location_title', None)
        if 'location' not in location:
            assert 'location' not in weibo
            weibo['location'] = location['location_title']

    return weibo
