from requests.exceptions import ProxyError, SSLError, ConnectionError

from sinaspider import UserConfig
from sinaspider.helper import logger


def loop(fetch_weibo, fetch_relation, download_dir):
    for uc in UserConfig.table.find(order_by='weibo_update_at'):
        uc = UserConfig(uc)
        while True:
            try:
                if fetch_weibo:
                    uc.fetch_weibo(download_dir)
                if fetch_relation:
                    uc.fetch_relation()
                break

            except (ProxyError, SSLError, ConnectionError):
                logger.warning('Internet seems broken, sleeping...')
                for i in range(600):
                    print(f'sleeping {600 - i - 1}', end='\r')
                continue
