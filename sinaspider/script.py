from requests.exceptions import ProxyError, SSLError, ConnectionError

from sinaspider import UserConfig, config
from sinaspider.helper import logger


from typer import Typer, Option

app = Typer()


@app.command()
def weibo(download_dir=config['download_dir']):
    for uc in UserConfig.table.find(order_by='weibo_update_at'):
        uc = UserConfig(uc)
        while True:
            try:
                uc.fetch_weibo(download_dir)
                break
            except (ProxyError, SSLError, ConnectionError):
                logger.warning('Internet seems broken, sleeping...')
                for i in range(600):
                    print(f'sleeping {600 - i - 1}', end='\r')
                continue


@app.command()
def relation():
    for uc in UserConfig.table.find(order_by='weibo_update_at'):
        uc = UserConfig(uc)
        while True:
            try:
                uc.fetch_relation()
                break
            except (ProxyError, SSLError, ConnectionError):
                logger.warning('Internet seems broken, sleeping...')
                for i in range(600):
                    print(f'sleeping {600 - i - 1}', end='\r')
                continue
