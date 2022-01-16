import os
import random
import time
from pathlib import Path
from time import sleep

import keyring
from baseconv import base62
from furl import furl
from requests.exceptions import SSLError
from requests_cache import CachedSession

from sinaspider import logger

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
            logger.error(f'{e}: Timeout sleep 600 seconds and retry {url}...')
            sleep(10 * 60)

    return r


def write_xmp(tags, img):
    try:
        import exiftool
    except ModuleNotFoundError:
        logger.warning(
            'exiftool not installed, cannot write xmp info to img')
        return

    with exiftool.ExifTool() as et:
        et.set_tags(tags, str(img))
        try:
            Path(img).with_name(Path(img).name + '_original').unlink()
        except FileNotFoundError:
            pass


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
            logger.critical(f'unsuppored pause mode {mode}')
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
        logger.info(f'waiting {sleep_time} second(s)...')
        to_sleep = self.__since + sleep_time - time.time()
        to_sleep = max(int(to_sleep), 0)
        for i in range(to_sleep):
            print(f'sleep {i}/{to_sleep}', end='\r')
            sleep(1)
        self.__since = time.time()


def convert_wb_bid_to_id(bid):
    id_ = ''
    bid = bid.swapcase()
    while bid:
        bid, num = bid[:-4], bid[-4:]
        num = base62.decode(num)
        id_ = f'{int(num):07d}{id_}'
    id_ = int(id_)
    return id_


pause = Pause()
