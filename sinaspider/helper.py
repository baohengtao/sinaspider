import itertools
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep
from typing import Iterable
from urllib.parse import unquote, urlparse

import pendulum
import requests
from baseconv import base62
from dotenv import load_dotenv
from exiftool import ExifToolHelper
from exiftool.exceptions import ExifToolExecuteException
from geopy.distance import geodesic
from requests.exceptions import ConnectionError

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError


def _get_session():
    env_file = Path(__file__).with_name('.env')
    load_dotenv(env_file)
    if not (cookie_main := os.getenv('COOKIE_MAIN')):
        raise ValueError(f'no main cookie found in {env_file}')
    if not (cookie_art := os.getenv('COOKIE_ART')):
        raise ValueError(f'no art cookie found in {env_file}')
    user_agent = (
        'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/100.0.4896.75 Mobile Safari/537.36')
    sess_main = requests.Session()
    sess_main.headers['User-Agent'] = user_agent
    sess_main.headers['Cookie'] = cookie_main
    sess_art = requests.Session()
    sess_art.headers['User-Agent'] = user_agent
    sess_art.headers['Cookie'] = cookie_art
    return sess_main, sess_art


sess_main, sess_art = _get_session()


class Fetcher:
    def __init__(self, art_login: bool = None) -> None:
        self.sess_main, self.sess_art = _get_session()
        self._visit_count = 0
        self._last_fetch = time.time()
        self._art_login = art_login

    @property
    def art_login(self):
        return self._art_login

    def toggle_art(self, on: bool = True):
        if self._art_login == on:
            return
        self._art_login = on
        url = (
            "https://api.weibo.cn/2/profile/me?launchid=10000365--x&from=10D9293010&c=iphone")
        s = '694a9ce0' if self.art_login else '537c037e'
        js = fetcher.get(url, params={'s': s}).json()
        screen_name = js['mineinfo']['screen_name']
        console.log(
            f'fetcher: current logined as {screen_name}',
            style='green on dark_green')

    def get(self, url: str,
            art_login: bool = None,
            params=None) -> requests.Response:
        # write with session and pause
        if art_login is None:
            if self.art_login is None:
                console.log(
                    'art_login is not set, set to True', style='warning')
                self.toggle_art(True)
            art_login = self.art_login

        self._pause()
        s = self.sess_art if art_login else self.sess_main
        while True:
            try:
                return s.get(url, params=params)
            except ConnectionError as e:
                period = 3600 if '/feed/friends' in url else 60
                console.log(
                    f"{e}: Sleepping {period} seconds and "
                    f"retry [link={url}]{url}[/link]...", style='error')
                sleep(period)

    def _pause(self):

        if time.time()-self._last_fetch > 1024:
            self._visit_count = 0
            console.log('reset visit count to zero', style='info')

        if self._visit_count == 0:
            self._visit_count = 1
            self._last_fetch = time.time()
            return

        if self._visit_count % 256 == 0:
            sleep_time = 256
        elif self._visit_count % 64 == 0:
            sleep_time = 64
        elif self._visit_count % 16 == 0:
            sleep_time = 16
        else:
            sleep_time = 1
        sleep_time *= random.uniform(0.5, 1.5)
        console.log(
            f'sleep {sleep_time:.1f} seconds...(count: {self._visit_count})',
            style='info')
        self._last_fetch = time.time() + sleep_time
        while time.time() < self._last_fetch:
            sleep(0.1)
        self._visit_count += 1


fetcher = Fetcher()
# fetcher.toggle_art(True)


def write_xmp(img: Path, tags: dict):
    for k, v in tags.copy().items():
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
    else:
        console.log(f'downloading {img}...', style="dim")
    if match := re.search(r'[\?&]Expires=(\d+)(&|$)', url):
        expires = pendulum.from_timestamp(int(match.group(1)), tz='local')
        if expires < pendulum.now():
            console.log(
                f"{url} expires at {expires}, skip...", style="warning")
            return
    while True:
        try:
            r = requests.get(url)
        except ConnectionError as e:
            period = 60
            console.log(
                f"{e}: Sleepping {period} seconds and "
                f"retry [link={url}]{url}[/link]...", style='error')
            sleep(period)
            continue

        if r.status_code == 404:
            console.log(
                f"{url}, {xmp_info}, {r.status_code}", style="error")
            return
        elif r.status_code != 200:
            console.log(f"{url}, {r.status_code}", style="error")
            time.sleep(15)
            console.log(f'retrying download for {url}...')
            continue

        if urlparse(r.url).path == '/images/default_d_w_large.gif':
            img = img.with_suffix('.gif')

        if int(r.headers['Content-Length']) != len(r.content):
            console.log(f"expected length: {r.headers['Content-Length']}, "
                        f"actual length: {len(r.content)} for {img}",
                        style="error")
            console.log(f'retrying download for {img}')
            continue

        img.write_bytes(r.content)

        if xmp_info:
            write_xmp(img, xmp_info)
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
        r = fetcher.get(f'https://weibo.cn/u/{user_id}', art_login=True)
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


def encode_wb_id(id_: int) -> str:
    id_, bid = str(id_), ''
    while id_:
        id_, num = id_[:-7], id_[-7:]
        enc = base62.encode(int(num)).swapcase().zfill(4)
        bid = enc + bid
    return bid.lstrip('0')


def normalize_str(amount):
    if amount and isinstance(amount, str):
        num, mul = amount[:-1], amount[-1]
        match mul:
            case '亿':
                amount = float(num) * (10 ** 8)
            case '万':
                amount = float(num) * (10 ** 4)
            case _:
                if amount.isnumeric():
                    amount = int(amount)

    return amount


def round_loc(lat: float | str, lng: float | str,
              tolerance: float = 0.01) -> tuple[float, float]:
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
    >> loc_src = ('https://m.weibo.cn/p/index?containerid='
                  '100808fcf3af2237af9eae5bb1c3f55951b731_-_lbs')
    >> parse_loc_src(loc_src)
        {
            'id': '8008646020000000000',
            'name': '三亚',
            'latitude': 18.247872,
            'longitude': 109.508268
            }
    """
    containerid = re.search(r'containerid=([\w-]+)', loc_src).group(1)
    api = ('https://m.weibo.cn/api/container/getIndex?'
           f'containerid={containerid}')
    js = fetcher.get(api).json()
    cards = js['data']['cards'][0]['card_group'][:2]
    name = cards[1]['group'][0]['item_title']
    lng, lat = re.search(r'longitude=(-?\d+\.\d+)&latitude=(-?\d+\.\d+)',
                         cards[0]['pic']).groups()
    fid = cards[0]['actionlog']['fid']
    location_id = re.match(r'2306570042(\w+)', fid).group(1)
    return dict(
        id=location_id,
        short_name=name,
        latitude=float(lat),
        longitude=float(lng),
    )
