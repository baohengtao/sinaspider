from sinaspider import UserConfig
from sinaspider.helpers import logger
from requests.exceptions import ProxyError, SSLError, ConnectionError
import click


@click.command()
@click.option('--fetch_weibo', '-w', is_flag=True)
def loop(fetch_weibo=True, fetch_relation=True, download_dir=None):
    for uc in UserConfig.table.find(order_by='weibo_update_at'):
        logger.info(uc)
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
                    print(f'sleeping {600-i-1}', end='\r')
                continue
