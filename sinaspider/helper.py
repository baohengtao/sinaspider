import asyncio
import itertools
import json
import logging
import mimetypes
import random
import re
import time
from pathlib import Path
from typing import AsyncIterable
from urllib.parse import unquote

import httpx
import magic
import pendulum
from baseconv import base62
from exiftool import ExifToolHelper
from geopy.distance import geodesic
from humanize import naturalsize
from makelive import is_live_photo_pair, live_id, make_live_photo
from makelive.makelive import (
    add_asset_id_to_image_file,
    add_asset_id_to_quicktime_file
)
from rich.prompt import Confirm

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError

httpx_logger = logging.getLogger("httpx")
httpx_logger.disabled = True
mime_detector = magic.Magic(mime=True)


class Fetcher:
    def __init__(self, art_login: bool | None = None) -> None:
        self.sess_main, self.sess_art = self.get_session()
        self._visit_count = 0
        self.visits = 0
        self._last_fetch = time.time()
        self._art_login = art_login

    def get_session(self):
        user_agent = (
            'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/100.0.4896.75 Mobile Safari/537.36')
        headers = {'User-Agent': user_agent}

        cookie_file = Path(__file__).with_name('cookie.json')
        if cookie_file.exists():
            cookies = json.loads(cookie_file.read_text())
        else:
            cookies = {}
        sess_main = httpx.AsyncClient(
            headers=headers, cookies=cookies.get('main'))
        sess_art = httpx.AsyncClient(
            headers=headers, cookies=cookies.get('art'))
        return sess_main, sess_art

    async def login(self, art_login: bool | None = None):

        if art_login is None:
            if (art_login := self.art_login) is None:
                raise ValueError('art_login is not set')
        sess = self.sess_art if art_login else self.sess_main
        url = (
            "https://api.weibo.cn/2/profile/me?launchid=10000365--x&from=10D9293010&c=iphone")
        s = '694a9ce0' if art_login else '537c037e'
        while True:
            js = await self.get_json(url, art_login, params={'s': s})
            if not js.get('errmsg'):
                break
            console.log(f'fetch {url} error: {js}', style='error')
            console.log(
                f'cookie expired, relogin...(art_login={art_login})',
                style='error')
            if not Confirm.ask('open browser to login?'):
                raise ValueError('cookie expired')
            self._set_cookie(sess)
        screen_name = js['mineinfo']['screen_name']
        return screen_name

    def _set_cookie(self, sess: httpx.Client):
        from selenium import webdriver
        browser = webdriver.Chrome()
        browser.get('https://m.weibo.cn')
        input('press enter after login...')
        sess.cookies = {c['name']: c['value'] for c in browser.get_cookies()}
        browser.quit()
        self.save_cookie()

    def save_cookie(self):
        cookie_file = Path(__file__).with_name('cookie.json')
        cookies = dict(
            main={c.name: c.value for c in self.sess_main.cookies.jar},
            art={c.name: c.value for c in self.sess_art.cookies.jar})
        cookie_file.write_text(json.dumps(cookies))

    @property
    def art_login(self):
        return self._art_login

    async def toggle_art(self, on: bool = True) -> None:
        if self._art_login == on:
            return
        self._art_login = on
        screen_name = await self.login(art_login=on)
        console.log(
            f'fetcher: current logined as {screen_name} (is_art:{on})',
            style='green on dark_green')

    async def request(self, method, url: str,
                      art_login: bool | None = None,
                      **kwargs) -> httpx.Response:
        # write with session and pause
        if art_login is None:
            if self.art_login is None:
                console.log(
                    'art_login is not set, set to True', style='warning')
                await self.toggle_art(True)
            art_login = self.art_login

        await self._pause()
        s = self.sess_art if art_login else self.sess_main
        while True:
            try:
                r = await s.request(method, url, **kwargs)
                r.raise_for_status()
            except asyncio.CancelledError:
                console.log(f'{method} {url}  was cancelled.', style='error')
                raise
            except httpx.HTTPError as e:
                period = 3600 if '/feed/friends' in url else 60
                console.log(
                    f"{e!r}: sleep {period} seconds and "
                    f"retry [link={url}]{url}[/link]...", style='error')
                await asyncio.sleep(period)
            else:
                assert r.status_code == 200
                return r

    async def get(self, url: str, art_login: bool = None,
                  **kwargs) -> httpx.Response:
        return await self.request('get', url, art_login, **kwargs)

    async def get_json(self, url: str, art_login: bool = None,
                       **kwargs) -> dict:
        r = await self.request('get', url, art_login, **kwargs)
        return r.json()

    async def post(self, url: str, art_login: bool = None,
                   **kwargs) -> httpx.Response:
        return await self.request('post', url, art_login, **kwargs)

    async def _pause(self):
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
                f'no activity for {-wait_time:.1f} seconds, '
                'which means more than 1 hour passed')
        else:
            console.log(
                f'no sleeping since more than {sleep_time:.1f} seconds passed'
                f'(count: {self._visit_count})')
        while time.time() < self._last_fetch:
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                console.log('Cancelled on sleep', style='error')
                raise KeyboardInterrupt
        self._last_fetch = time.time()
        self._visit_count += 1


fetcher = Fetcher()
client = httpx.AsyncClient(follow_redirects=True)
et = ExifToolHelper()


def write_xmp(img: Path, tags: dict):
    for k, v in tags.copy().items():
        if isinstance(v, str):
            tags[k] = v.replace('\n', '&#x0a;')
    params = ['-overwrite_original', '-ignoreMinorErrors', '-escapeHTML']
    ext = et.get_tags(img, 'File:FileTypeExtension')[
        0]['File:FileTypeExtension'].lower()
    if (suffix := f'.{ext}') != img.suffix:
        raise ValueError(f'{img} suffix is not right: {suffix}')
        # new_img = img.with_suffix(suffix)
        # console.log(
        #     f'{img}: suffix is not right, moving to {new_img}...',
        #     style='error')
        # img = img.rename(new_img)
    et.set_tags(img, tags, params=params)


semaphore = asyncio.Semaphore(8)


async def download_file_pair(medias: list[dict]):
    if len(medias) == 1:
        await download_single_file(**medias[0])
        return
    img_info, mov_info = medias
    img_xmp = img_info.pop('xmp_info')
    mov_xmp = mov_info.pop('xmp_info')
    try:
        img_path = await download_single_file(**img_info)
        mov_path = await download_single_file(**mov_info)
    except Exception:
        if (img_path := img_info['filepath']/img_info['filename']).exists():
            img_path.unlink()
        if (mov_path := mov_info['filepath']/mov_info['filename']).exists():
            mov_path.unlink()
        raise
    if mov_path is None or mov_path.suffix not in {'.mov', '.mp4'}:
        console.log(f'live mov download failed: {mov_info}', style='error')
        write_xmp(img_path, img_xmp)
        if mov_path:
            write_xmp(mov_path, mov_xmp)
        return
    img_size = naturalsize(img_path.stat().st_size)
    mov_size = naturalsize(mov_path.stat().st_size)
    if not is_live_photo_pair(img_path, mov_path):
        # assert not (live_id(img_path) and live_id(mov_path))
        console.log(
            f'not live photo pair: {img_path} {mov_path}, fixing...',
            style='warning')
        if assert_id := live_id(img_path):
            add_asset_id_to_quicktime_file(mov_path, assert_id)
        elif assert_id := live_id(mov_path):
            add_asset_id_to_image_file(img_path, assert_id)
        else:
            make_live_photo(img_path, mov_path)
    if (x := naturalsize(img_path.stat().st_size)) != img_size:
        console.log(f'{img_path.name} size changed from {img_size} to {x}')
    if (x := naturalsize(mov_path.stat().st_size)) != mov_size:
        console.log(f'{mov_path.name} size changed from {mov_size} to {x}')
    assert is_live_photo_pair(img_path, mov_path)
    write_xmp(img_path, img_xmp)
    write_xmp(mov_path, mov_xmp)


async def download_single_file(
        url: str,
        filepath: Path,
        filename: str,
        xmp_info: dict = None
) -> Path | None:
    filepath.mkdir(parents=True, exist_ok=True)
    img = filepath / filename
    if img.exists():
        console.log(f'{img} already exists..skipping...', style='info')
        return img
    if match := re.search(r'[\?&]Expires=(\d+)(&|$)', url):
        expires = pendulum.from_timestamp(int(match.group(1)), tz='local')
        if expires < pendulum.now():
            console.log(
                f"{url} expires at {expires}, skip...", style="warning")
            return
    for i in range(10):
        async with semaphore:
            if i:
                period = 60
                await asyncio.sleep(period)
            try:
                r = await client.get(url)
            except httpx.HTTPError as e:
                if i > 0:
                    console.log(f'download img {img} failed with {e!r} ({url})...'
                                f' retry in {period} seconds...(has tried {i} time(s))',
                                style='error')
                continue

        if r.status_code in [404, 403]:
            if i == 0:
                continue
            elif i < 3:
                console.log(f'{url} {r.status_code} ERROR, has tried {i} time(s)',
                            style='error')
                continue
            else:
                console.log(
                    f"failed downloading {url}, {xmp_info or img}, {r.status_code}", style="error")
                return
        elif r.status_code != 200:
            console.log(f"{url}, {r.status_code}", style="error")
            console.log(f'retrying download for {url}...')
            continue

        mime_type = mime_detector.from_buffer(r.content)
        if mime_type != 'application/octet-stream':
            suffix = mimetypes.guess_extension(mime_type)
        else:
            suffix = img.suffix
        if suffix == '.gif':
            assert r.url.path.endswith('.gif')
            if not url.endswith('.gif'):
                assert r.url.path.endswith(
                    ('/images/default_d_h_large.gif',
                     '/images/default_d_w_large.gif',
                     '/images/default_w_large.gif',
                     '/images/default_h_large.gif',
                     '/images/default_s_large.gif',)), r.url.path
                if i == 0:
                    continue
                elif i < 5:
                    console.log(
                        f"{url} shouldn't be gif, but redirected to {r.url} "
                        f"(has tried {i} time(s))",
                        style='error')
                    continue
                else:
                    console.log(
                        f'{img}: seems be deleted ({url})', style='error')
            img = img.with_suffix('.gif')

        elif img.suffix != suffix:
            console.log(f"{img}: suffix should be {suffix}", style="warning")
            img = img.with_suffix(suffix)

        if int(r.headers['Content-Length']) != len(r.content):
            console.log(f"expected length: {r.headers['Content-Length']}, "
                        f"actual length: {len(r.content)} for {img}",
                        style="error")
            console.log(f'retrying download for {img}')
            continue

        img.write_bytes(r.content)

        if xmp_info:
            write_xmp(img, xmp_info)
        console.log(f'successfully downloaded: {img}...', style="dim")
        return img
    else:
        raise ValueError(f'cannot download {url} for {img}')


async def download_files(imgs: AsyncIterable[list[dict]]):
    tasks = []
    async for img in imgs:
        task = asyncio.create_task(download_file_pair(img))
        tasks.append(task)
        for x in [1000, 100, 10, 1]:
            if len(tasks) % x == 0:
                await asyncio.sleep(0.1*x)
                break
    await asyncio.gather(*tasks)


async def normalize_user_id(user_id: str | int) -> int:
    """
    Normalize user_id to int.

    Raise UserNotFoundError if user_id not exist.
    """
    try:
        user_id = int(user_id)
    except ValueError:
        assert isinstance(user_id, str)
        url = f'https://m.weibo.cn/n/{user_id}'
        r = await fetcher.get(url, follow_redirects=True)
        url_new = str(r.url)
        if url != unquote(url_new):
            user_id = int(url_new.split('/')[-1])
        else:
            raise UserNotFoundError(f'{user_id} not exist')
    else:
        r = await fetcher.get(f'https://weibo.cn/u/{user_id}', art_login=True)
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
    try:
        id_ = int(id_)
    except ValueError:
        return id_
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

    for precision in itertools.count(start=1):
        lat_, lng_ = round(lat, precision), round(lng, precision)
        if geodesic((lat, lng), (lat_, lng_)).meters < tolerance:
            return lat_, lng_


async def parse_loc_src(loc_src: str) -> str:
    """
    >> loc_src = ('https://m.weibo.cn/p/index?containerid='
                  '100808fcf3af2237af9eae5bb1c3f55951b731_-_lbs')
    >> parse_loc_src(loc_src)
        '8008646020000000000'
    """
    containerid = re.search(r'containerid=([\w-]+)', loc_src).group(1)
    api = ('https://m.weibo.cn/api/container/getIndex?'
           f'containerid={containerid}')
    js = await fetcher.get_json(api)
    cards = js['data']['cards'][0]['card_group']
    params = cards[1]['scheme'].split('?')[-1].split('&')
    params = dict(p.split('=') for p in params)
    if not (location_id := params.get('extparam')):
        containerid = params['containerid']
        location_id = re.match(
            '2310360016([\w-]+)_pic', containerid).group(1)
    return location_id
