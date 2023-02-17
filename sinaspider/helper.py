import itertools
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep
from typing import Iterator
from urllib.parse import unquote, urlparse

import keyring
import pendulum
import requests
from baseconv import base62
from exiftool import ExifToolHelper
from exiftool.exceptions import ExifToolExecuteException
from furl import furl
from requests.exceptions import ConnectionError, ProxyError, SSLError

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError

weibo_api_url = furl(url='https://m.weibo.cn', path='api/container/getIndex')
user_agent = ('Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/100.0.4896.75 Mobile Safari/537.36')
headers = {
    "User-Agent": user_agent,
    "Cookie": keyring.get_password('sinaspider', 'cookie'),
    "referer": "https://m.weibo.cn",
}


def get_url(url: str) -> requests.Response:

    while True:
        try:
            return requests.get(url, headers=headers)
        except (TimeoutError, ConnectionError, SSLError, ProxyError) as e:
            if type(e) is ConnectionError:
                period = 600
            elif type(e) is SSLError:
                period = 5
            else:
                period = 60
            console.log(
                f"{e}: Timeout sleep {period} seconds and "
                f"retry[link={url}]{url}[/link]...", style='error')
            sleep(period)


def parse_url_extension(url: str) -> str:
    parse = urlparse(url)
    return Path(parse.path).suffix or Path(url).suffix


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


def normalize_user_id(user_id: str | int) -> int:
    """
    normalize user_id to int
    raise UserNotFoundError if user_id not exist
    """
    try:
        user_id = int(user_id)
    except ValueError:
        assert isinstance(user_id, str)
        url = f'https://m.weibo.cn/n/{user_id}'
        r = get_url(url)
        if url != unquote(r.url):
            user_id = int(r.url.split('/')[-1])
        else:
            raise UserNotFoundError(f'{user_id} not exist')
    else:
        r = get_url(f'https://weibo.cn/u/{user_id}')
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


def download_single_file(
        url: str, filepath: Path, filename: str, xmp_info: dict = None):
    filepath.mkdir(parents=True, exist_ok=True)
    img = filepath / filename
    if img.exists():
        console.log(f'{img} already exists..skipping...', style='info')
        return

    if expires := furl(url).args.get("Expires"):
        expires = pendulum.from_timestamp(int(expires), tz='local')
        if expires < pendulum.now():
            console.log(
                f"{url} expires at {expires}, skip...", style="warning")
            return
    for tried_time in itertools.count(start=1):
        while (r := get_url(url)).status_code != 200:
            console.log(f"{url}, {r.status_code}", style="error")
            if r.status_code == 404:
                return
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


def download_files(imgs: Iterator[dict]):
    # TODO: gracefully handle exception and keyboardinterrupt
    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = [pool.submit(download_single_file, **img) for img in imgs]
    for future in futures:
        future.result()


class Pause:
    def __init__(self):

        self.page_config = dict(
            awake=0,
            stop=random.randint(5, 9),
            visited=0,
            level={
                'short': 5,
                'break': 10,
                'long': 120,
            },
            break_freq=25
        )
        self.user_config = dict(
            awake=0,
            stop=random.randint(2, 4),
            visited=0,
            level={
                'short': 5,
                'break': 15,
                'long': 20,
            },
            break_freq=10
        )

        self.__since = time.time()

    def __call__(self, mode: str):
        if mode == 'page':
            self._pause(self.page_config)
        elif mode == 'user':
            self._pause(self.user_config)
        else:
            raise ValueError(f'unsupported pause mode {mode}')

    def _pause(self, record):
        awake, stop = record['awake'], record['stop']
        level, break_freq = record['level'], record['break_freq']
        record['visited'] += 1
        if awake < stop:
            record['awake'] += 1
            self._sleep(level['short'])
        elif awake == stop:
            record['awake'] = 0
            self._sleep(level['break'])
            record['stop'] = random.randint(2, 4)
        if record['visited'] % break_freq == 0:
            self._sleep(level['long'])

    def _sleep(self, sleep_time):
        sleep_time = random.randint(
            int(0.5 * sleep_time), int(1.5 * sleep_time))
        to_sleep = self.__since + sleep_time - time.time()
        if to_sleep := max(int(to_sleep), 0):
            console.log(f'sleep {to_sleep} seconds...')
            sleep(to_sleep)

        self.__since = time.time()


pause = Pause()
