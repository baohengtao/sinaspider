import os
import random
import sys
from functools import partial
from time import sleep

import keyring
import requests
from baseconv import base62
from configobj import ConfigObj
from loguru import logger

logger.remove()
logger.add(sys.stdout, colorize=True)

_configpath = os.environ.get('XDG_CACHE_HOME') or os.environ.get('HOME')
CONFIG_FILE = os.path.join(_configpath, 'sinaspider.ini')


def config(account_id=None, database_name=None, write_xmp=None):
    """
    写入并读取配置
    Args:
        account_id: 自己微博账号id
        database_name: 数据库名称
        write_xmp: 是否将微博信息写入照片
    Returns:
        [dict]: 当前的配置信息
    """
    default = {'database_name': 'sina', 'write_xmp': False}
    config = ConfigObj(CONFIG_FILE)
    config.update(default | config)
    if account_id is not None:
        config['account_id'] = account_id
    if database_name is not None:
        config['database_name'] = database_name
    if write_xmp is not None:
        assert isinstance(write_xmp, bool)
        config['write_xmp'] = write_xmp
    config.write()
    return config


headers = {
    "User_Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:90.0) Gecko/20100101 Firefox/90.0",
    "Cookie": keyring.get_password('sinaspider', 'cookie')
}

get_url = partial(requests.get, headers=headers)


def get_json(**params):
    url = 'https://m.weibo.cn/api/container/getIndex?'
    while True:
        try:
            r = get_url(url, params=params)
            break
        except TimeoutError:
            logger.error('Timeout sleep 600seconds and retry...')
            sleep(10 * 60)

    return r.json()


class Pause:
    def __init__(self):

        self.page_config = dict(
            awake=0,
            stop=random.randint(3, 5),
            visited=0,
            level={
                'short': 5,
                'break': 20,
                'long': 50
            },
            break_freq=100
        )
        self.user_config = dict(
            awake=0,
            stop=random.randint(2, 4),
            visited=0,
            level={
                'short': 10,
                'break': 60,
                'long': 200
            },
            break_freq=10
        )

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

    @staticmethod
    def _sleep(sleep_time):
        sleep_time = random.randint(int(0.5 * sleep_time), int(1.5 * sleep_time))

        for i in range(sleep_time):
            print(f'sleep {i}/{sleep_time}', end='\r')
            sleep(1)


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
