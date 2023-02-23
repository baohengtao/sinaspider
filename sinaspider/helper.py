import itertools
import random
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
from furl import furl
from requests.exceptions import ConnectionError, ProxyError, SSLError

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError


def get_pause():
    count = 0
    sleep_until = time.time()

    def _sleep(sleep_time):
        nonlocal sleep_until
        sleep_time = random.uniform(0.5 * sleep_time, 1.5 * sleep_time)
        console.log(
            f'sleep {sleep_time:.1f} seconds...(count: {count})', style='info')
        sleep_until = time.time() + sleep_time
        while time.time() < sleep_until:
            sleep(1)

    def pause():
        nonlocal count
        if time.time() - sleep_until > 3600:
            count = 0
        count += 1
        if count % 128 == 0:
            sleep_time = 256
        elif count % 64 == 0:
            sleep_time = 64
        elif count % 16 == 0:
            sleep_time = 16
        else:
            sleep_time = 0.1
        _sleep(sleep_time)
    return pause


_pause = get_pause()

user_agent = ('Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/100.0.4896.75 Mobile Safari/537.36')
headers = {
    "User-Agent": user_agent,
    "Cookie": keyring.get_password('sinaspider', 'cookie'),
    "referer": "https://m.weibo.cn",
}


def fetch_url(url: str, mainthread=True) -> requests.Response:
    # write with session and pause
    if mainthread:
        _pause()
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
                f"retry [link={url}]{url}[/link]...", style='error')
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
    Normalize user_id to int.

    Raise UserNotFoundError if user_id not exist.
    """
    try:
        user_id = int(user_id)
    except ValueError:
        assert isinstance(user_id, str)
        url = f'https://m.weibo.cn/n/{user_id}'
        r = fetch_url(url)
        if url != unquote(r.url):
            user_id = int(r.url.split('/')[-1])
        else:
            raise UserNotFoundError(f'{user_id} not exist')
    else:
        r = fetch_url(f'https://weibo.cn/u/{user_id}')
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
        while (r := fetch_url(url, mainthread=False)).status_code != 200:
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


def download_files(imgs: Iterable[dict]):
    # TODO: gracefully handle exception and keyboardinterrupt
    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = [pool.submit(download_single_file, **img) for img in imgs]
    for future in futures:
        future.result()
