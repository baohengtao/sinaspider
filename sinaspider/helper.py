import itertools
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep
from typing import Iterable
from urllib.parse import unquote, urlparse

import keyring
import pendulum
import requests
from baseconv import base62
from exiftool import ExifToolHelper
from exiftool.exceptions import ExifToolExecuteException
from geopy.distance import geodesic
from requests.exceptions import ConnectionError

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError


class Fetcher:
    def __init__(self) -> None:
        self.sess = requests.Session()
        self.sess.headers['User-Agent'] = (
            'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/100.0.4896.75 Mobile Safari/537.36')
        self.sess.headers['Cookie'] = keyring.get_password(
            'sinaspider', 'cookie')
        self._visit_count = 0
        self._sleep_until = time.time()

    def get(self, url: str, mainthread=True) -> requests.Response:
        # write with session and pause
        if mainthread:
            self._pause()
        get = self.sess.get if mainthread else requests.get
        while True:
            try:
                return get(url)
            except ConnectionError as e:
                period = 60
                console.log(
                    f"{e}: Sleepping {period} seconds and "
                    f"retry [link={url}]{url}[/link]...", style='error')
                sleep(period)

    def _pause(self):
        if time.time() - self._sleep_until > 1024:
            self._visit_count = 0
        self._visit_count += 1
        if self._visit_count % 256 == 0:
            sleep_time = 256
        elif self._visit_count % 64 == 0:
            sleep_time = 64
        elif self._visit_count % 16 == 0:
            sleep_time = 16
        else:
            sleep_time = 0.1
        sleep_time *= random.uniform(0.5, 1.5)
        console.log(
            f'sleep {sleep_time:.1f} seconds...(count: {self._visit_count})',
            style='info')
        self._sleep_until = time.time() + sleep_time
        while time.time() < self._sleep_until:
            sleep(1)


fetcher = Fetcher()


def write_xmp(img: Path, tags: dict):
    for k, v in tags.items():
        if isinstance(v, str):
            tags[k] = v.replace('\n', '&#x0a;')
    params = ['-overwrite_original', '-ignoreMinorErrors', '-escapeHTML']
    with ExifToolHelper() as et:
        ext = et.get_tags(img, 'File:FileTypeExtension')[
            0]['File:FileTypeExtension'].lower()
        if (suffix := f'.{ext}') != img.suffix:
            new_img = img.with_suffix(suffix)
            console.log(
                f'{img}: suffix is not right, moving to {new_img}...',
                style='error')
            img = img.rename(new_img)
        et.set_tags(img, tags, params=params)


def download_single_file(
        url: str,
        filepath: Path,
        filename: str,
        xmp_info: dict = None
):
    # TODO: refactor this function
    filepath.mkdir(parents=True, exist_ok=True)
    img = filepath / filename
    if img.exists():
        console.log(f'{img} already exists..skipping...', style='info')
        return
    if match := re.search(r'[\?&]Expires=(\d+)(&|$)', url):
        expires = pendulum.from_timestamp(int(match.group(1)), tz='local')
        if expires < pendulum.now():
            console.log(
                f"{url} expires at {expires}, skip...", style="warning")
            return
    for tried_time in itertools.count(start=1):
        while (r := fetcher.get(url, mainthread=False)).status_code != 200:
            if r.status_code == 404:
                console.log(
                    f"{url}, {xmp_info}, {r.status_code}", style="error")
                return
            else:
                console.log(f"{url}, {r.status_code}", style="error")
            time.sleep(15)
            console.log(f'retrying download for {url}...')

        if urlparse(r.url).path == '/images/default_d_w_large.gif':
            img = img.with_suffix('.gif')

        img.write_bytes(r.content)

        if xmp_info:
            try:
                write_xmp(img, xmp_info)
            except ExifToolExecuteException as e:
                console.log(e.stderr, style='error')
                if tried_time < 3:
                    console.log(
                        f'{img}:write xmp failed, retrying {url}',
                        style='error')
                    continue
                img_failed = img.parent / 'problem' / img.name
                img_failed.parent.mkdir(parents=True, exist_ok=True)
                img.rename(img_failed)
                console.log(f'move {img} to {img_failed}', style='error')
                raise e
        break


def download_files(imgs: Iterable[dict]):
    # TODO: gracefully handle exception and keyboardinterrupt
    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = [pool.submit(download_single_file, **img) for img in imgs]
    for future in futures:
        future.result()


def parse_url_extension(url: str) -> str:
    parse = urlparse(url)
    return Path(parse.path).suffix or Path(url).suffix


def normalize_user_id(user_id: str | int) -> int:
    """
    Normalize user_id to int.

    Raise UserNotFoundError if user_id not exist.
    """
    try:
        user_id = int(user_id)
    except ValueError:
        assert isinstance(user_id, str)
        url = f'https://m.weibo.cn/n/{user_id}'
        r = fetcher.get(url)
        if url != unquote(r.url):
            user_id = int(r.url.split('/')[-1])
        else:
            raise UserNotFoundError(f'{user_id} not exist')
    else:
        r = fetcher.get(f'https://weibo.cn/u/{user_id}')
        if 'User does not exists!' in r.text:
            raise UserNotFoundError(f'{user_id} not exist')
    return user_id


def normalize_wb_id(wb_id: int | str) -> int:
    try:
        return int(wb_id)
    except ValueError:
        pass
    assert isinstance(wb_id, str)
    id_ = ''
    bid = wb_id.swapcase()
    while bid:
        bid, num = bid[:-4], bid[-4:]
        num = base62.decode(num)
        id_ = f'{int(num):07d}{id_}'
    id_ = int(id_)
    return id_


def normalize_str(amount):
    if amount and isinstance(amount, str):
        num, mul = amount[:-1], amount[-1]
        match mul:
            case '亿':
                amount = float(num) * (10 ** 8)
            case '万':
                amount = float(num) * (10 ** 4)
    return amount


def round_loc(lat: float | str, lng: float | str, tolerance: float = 0.01) -> tuple[float, float]:
    """
    return rounded location with err small than tolerance meter
    """
    lat, lng = float(lat), float(lng)
    while True:
        for precision in itertools.count(start=1):
            lat_, lng_ = round(lat, precision), round(lng, precision)
            if (err := geodesic((lat, lng), (lat_, lng_)).meters) < tolerance:
                break
        if err:
            console.log(
                f'round loction: {lat, lng} -> {lat_, lng_} '
                f'with precision {precision} (err: {err}m)')
            lat, lng = lat_, lng_
        else:
            break
    return lat_, lng_


def parse_loc_src(loc_src: str) -> dict:
    """
    >> loc_src = 'https://m.weibo.cn/p/index?containerid=100808fcf3af2237af9eae5bb1c3f55951b731_-_lbs'
    >> parse_loc_src(loc_src)
        {
            'id': '8008646020000000000',
            'name': '三亚',
            'latitude': 18.247872,
            'longitude': 109.508268
            }
    """
    containerid = re.search(r'containerid=([\w-]+)', loc_src).group(1)
    api = f'https://m.weibo.cn/api/container/getIndex?containerid={containerid}'
    js = fetcher.get(api).json()
    cards = js['data']['cards'][0]['card_group'][:2]
    name = cards[1]['group'][0]['item_title']
    lng, lat = re.search(
        'longitude=(-?\d+\.\d+)&latitude=(-?\d+\.\d+)', cards[0]['pic']).groups()
    fid = cards[0]['actionlog']['fid']
    location_id = re.match('2306570042(\w+)', fid).group(1)
    return dict(
        id=location_id,
        short_name=name,
        latitude=float(lat),
        longitude=float(lng),
    )
