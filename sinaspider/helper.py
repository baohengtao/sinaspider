import itertools
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

import pendulum
import requests
from baseconv import base62
from dotenv import load_dotenv
from exiftool import ExifToolHelper
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
        self.visits = 0
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
                r = s.get(url, params=params)
                r.raise_for_status()
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.HTTPError) as e:
                period = 3600 if '/feed/friends' in url else 60
                console.log(
                    f"{e}: Sleepping {period} seconds and "
                    f"retry [link={url}]{url}[/link]...", style='error')
                time.sleep(period)
            else:
                assert r.status_code == 200
                return r

    def _pause(self):
        self.visits += 1
        if self._visit_count == 0:
            self._visit_count = 1
            self._last_fetch = time.time()
            return
        for flag in [2048, 1024, 256, 64, 16]:
            if self._visit_count % flag == 0:
                sleep_time = flag
                break
        else:
            sleep_time = 1
        sleep_time *= random.uniform(0.5, 1.5)
        self._last_fetch += sleep_time
        if (wait_time := (self._last_fetch-time.time())) > 0:
            console.log(
                f'sleep {wait_time:.1f} seconds...'
                f'(count: {self._visit_count})',
                style='info')
        elif wait_time < -3600:
            self._visit_count = 0
            console.log(
                f'reset visit count to {self._visit_count} since have '
                f'no activity for {wait_time:.1f} seconds, '
                'which means more than 1 hour passed')
        else:
            console.log(
                f'no sleeping since more than {sleep_time:.1f} seconds passed'
                f'(count: {self._visit_count})')
        while time.time() < self._last_fetch:
            time.sleep(0.1)
        self._last_fetch = time.time()
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
            time.sleep(period)
            continue

        if r.status_code in [404, 302]:
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


def parse_loc_src(loc_src: str) -> str:
    """
    >> loc_src = ('https://m.weibo.cn/p/index?containerid='
                  '100808fcf3af2237af9eae5bb1c3f55951b731_-_lbs')
    >> parse_loc_src(loc_src)
        '8008646020000000000'
    """
    containerid = re.search(r'containerid=([\w-]+)', loc_src).group(1)
    api = ('https://m.weibo.cn/api/container/getIndex?'
           f'containerid={containerid}')
    js = fetcher.get(api).json()
    cards = js['data']['cards'][0]['card_group']
    name = cards[0]['group'][0]['item_title']
    params = cards[1]['scheme'].split('?')[-1].split('&')
    params = dict(p.split('=') for p in params)
    if not (location_id := params.get('extparam')):
        containerid = params['containerid']
        location_id = re.match(
            '2310360016([\w-]+)_pic', containerid).group(1)
    console.log(f'parsing {loc_src}', style='warning')
    console.log(
        f'location_id: {location_id}, short_name: {name}', style='warning')
    return location_id
