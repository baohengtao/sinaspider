
from sinaspider import console


def parse_photos_info(info: dict) -> list[str]:
    if info['pic_num'] == 0:
        return []
    if 'pic_infos' in info:
        pic_infos = [info['pic_infos'][pic_id]
                     for pic_id in info['pic_ids']]
        photos = [[pic_info['largest']['url'], pic_info.get('video', '')]
                  for pic_info in pic_infos]
    elif pics := info.get('pics'):
        pics = pics.values() if isinstance(pics, dict) else pics
        pics = [p for p in pics if 'pid' in p]
        photos = [[pic['large']['url'], pic.get('videoSrc', '')]
                  for pic in pics]
    elif page_info := info.get('page_info'):
        assert info['pic_num'] == 1
        page_pic = page_info['page_pic']
        url = page_pic if isinstance(
            page_pic, str) else page_pic['url']
        photos = [[url, '']]
    else:
        assert info['pic_num'] == 1
        for struct in info['url_struct']:
            if 'pic_infos' in struct:
                break
        pic_infos = [struct['pic_infos'][pic_id]
                     for pic_id in struct['pic_ids']]
        photos = [[pic_info['largest']['url'], pic_info.get('video', '')]
                  for pic_info in pic_infos]
        info = struct

    for p in photos:
        if p[0].endswith('.gif'):
            if p[1] and ('https://video.weibo.com/media/play?fid=' not in p[1]):
                assert "://g.us.sinaimg.cn/" in p[1]
            p[1] = ''
        else:
            p[1] = p[1].replace("livephoto.us.sinaimg.cn", "us.sinaimg.cn")
    assert len(photos) == len(info['pic_ids'])
    photos = ["🎀".join(p).strip("🎀") for p in photos]
    return photos


def parse_photos_info_from_hist(hist_mblogs) -> tuple[list[str], int]:
    photos, ori_num = [], None
    for mblog in hist_mblogs:
        try:
            ps = parse_photos_info(mblog)
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


def parse_location_info_from_hist(hist_mblogs) -> dict | None:
    if not hist_mblogs:
        return
    regions = []
    for mblog in hist_mblogs:
        if region_name := mblog.get('region_name'):
            region_name = region_name.removeprefix('发布于').strip()
        if region_name == '其他':
            region_name = None
        regions.append(region_name)

    locations_from_url = []
    for mblog in hist_mblogs:
        url_struct = mblog.get('url_struct', [])
        pos = [u for u in url_struct if u.get('object_type') == 'place']
        if not pos:
            locations_from_url.append(None)
            continue
        assert len(pos) == 1
        pos = pos[0]
        page_id = pos['page_id']
        assert page_id.startswith('100101')
        location_id = page_id.removeprefix('100101')
        location = pos['url_title']
        locations_from_url.append({
            'location': location,
            'location_id': location_id,
        })

    locations = []
    for mblog in hist_mblogs:
        # parse tag_struct
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

        # parse geo
        if geo := mblog.get('geo'):
            assert geo['type'] == 'Point'
            lat, lng = geo['coordinates']
            assert list(geo.keys()) == ['type', 'coordinates']
            geo = {
                'latitude': lat,
                'longitude': lng,
            }

        # parse annotations
        annotations = [a for a in mblog.get(
            'annotations', []) if 'place' in a]
        assert len(annotations) <= 1
        if annotations:
            annotations = annotations[0]['place']
            annotations = {
                'title': annotations['title'],
                'location_id': annotations['poiid'],
            }

        # merge annotations to tag_struct or geo
        if tag_struct:
            assert annotations
            assert tag_struct['location_id'] == annotations['location_id']
            tag_struct |= annotations
        elif geo:
            assert annotations
            geo |= annotations
        else:
            locations.append(annotations or None)
            continue

        if tag_struct and geo:
            locations.append(tag_struct | geo)
        elif not geo:
            locations.append(tag_struct)
        else:
            locations.append(geo)

    assert len(locations) == len(
        locations_from_url) == len(hist_mblogs)
    if locations == [None] * len(locations):
        locations = locations_from_url
    else:
        assert locations_from_url == [None] * len(locations)

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

            console.log(
                '>>>>no location found, using title instead<<<<<',
                style='warning')
            console.log(location)
            console.log(
                '<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<',
                style='warning')

    else:
        for region in regions:
            if region:
                break
        location = locations[0]
        assert locations == [None] * len(locations)

    rs, ls = [], []
    for r, l in zip(regions, locations):
        if r not in rs:
            rs.append(r)
        if l not in ls:
            ls.append(l)
    if len(rs) > 1:
        console.log(
            '>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>',
            style='warning')
        console.log(f'multi region found: {rs},  {region} is chosen')
        console.log(
            '<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<',
            style='warning')
    if len(ls) > 1:
        console.log('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>',
                    style='warning')
        console.log(ls)
        console.log(
            f'multi location found,  {location} is chosen')
        console.log('<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<',
                    style='warning')

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
    if weibo.get('region_name') != regions[-1]:
        console.log(
            '>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>',
            style='warning')
        console.log('region not match: ')
        console.log(f'regions in hist: {regions}')
        console.log(f'region in weibo: {weibo.get("region_name")}')
        console.log('<'*50, style='warning')

    # compare location
    if not weibo.get('location'):
        if locations[-1] and ('weico' not in weibo.get('mblog_from', '')):
            assert 'location' not in locations[-1]
            console.log(
                '>>>>>>>>>>>location not found but geo is in there<<<<<<<<<<<<<<',
                style='warning')
            console.log(locations[-1])
            console.log('>'*60, style='warning')
    else:
        assert weibo['location'] == locations[-1]['location']
        assert weibo['location_id'] == locations[-1]['location_id']

    weibo['region_name'] = weibo.pop('selected_region')
    if location := weibo.pop('selected_location'):
        weibo |= location
        weibo.pop('title', None)
        if 'location' not in location:
            assert 'location' not in weibo
            weibo['location'] = location['title']

    if loc := weibo.get('location'):
        text = weibo['text'].removesuffix('📍')
        assert not text.endswith('📍')
        text += f' 📍{loc}'
        weibo['text'] = text.strip()

    return weibo
