import os
import random
import time
from pathlib import Path
from time import sleep
from typing import Optional

import keyring
from baseconv import base62
from furl import furl
from requests.exceptions import SSLError
from requests_cache import CachedSession

from sinaspider import console

weibo_api_url = furl(url='https://m.weibo.cn', path='api/container/getIndex')

headers = {
    "User_Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:90.0) Gecko/20100101 Firefox/90.0",
    "Cookie": keyring.get_password('sinaspider', 'cookie')
}


def get_url(url, expire_after=0):
    xdg_cache_home = os.environ.get('XDG_CACHE_HOME') or os.environ.get('HOME')
    session = CachedSession(
        cache_name=f'{xdg_cache_home}/sinaspider/http_cache')

    if expire_after == 0:
        session.cache.delete_url(url)

    while True:
        try:
            r = session.get(url, headers=headers, expire_after=expire_after)
            break
        except (TimeoutError, ConnectionError, SSLError) as e:
            console.log(f'{e}: Timeout sleep 600 seconds and retry [link={url}]{url}[/link]...', style='error')
            sleep(10 * 60)

    return r


def write_xmp(tags, img):
    try:
        import exiftool
    except ModuleNotFoundError:
        console.log(
            'exiftool not installed, cannot write xmp info to img', style='error')
        return

    with exiftool.ExifTool() as et:
        et.set_tags(tags, str(img))
        try:
            Path(img).with_name(Path(img).name + '_original').unlink()
        except FileNotFoundError:
            pass


def convert_user_nick_to_id(users: str):
    users = [u for u in users.split() if u]
    for user_id in users:
        if not user_id.isdigit():
            r = get_url(f'https://m.weibo.cn/n/{user_id}')
            user_id = r.url.split('/')[-1]
        yield int(user_id)


def normalize_user_id(user_id) -> Optional[int]:
    from urllib.parse import unquote
    try:
        return int(user_id)
    except ValueError:
        pass
    assert isinstance(user_id, str)
    url = f'https://m.weibo.cn/n/{user_id}'
    r = get_url(url)
    if url != unquote(r.url):
        user_id = r.url.split('/')[-1]
        return int(user_id)
    else:
        console.log(f'{url} not exist', style='warning')
        return


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


def download_single_file(url, filepath: Path, filename, xmp_info=None):
    filepath.mkdir(parents=True, exist_ok=True)
    img = filepath / filename
    if img.exists():
        console.log(f'{img} already exists..skipping...', style='info')
        return
    while True:
        downloaded = get_url(url).content
        if len(downloaded) == 153:
            continue
        else:
            if len(downloaded) < 1024:
                console.log([len(downloaded), url, filepath], style='warning')
            break

    img.write_bytes(downloaded)
    if xmp_info:
        write_xmp(xmp_info, img)


def download_files(imgs):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as pool:
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

    def __call__(self, mode):
        if mode == 'page':
            self._pause(self.page_config)
        elif mode == 'user':
            self._pause(self.user_config)
        else:
            console.log(f'unsupported pause mode {mode}', style='error')
            assert False

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
