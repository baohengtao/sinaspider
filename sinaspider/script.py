from requests.exceptions import ProxyError, SSLError, ConnectionError

from sinaspider import UserConfig, config
from sinaspider.helper import logger

from typer import Typer, Option, Argument

app = Typer()

@app.command()
def loop(fetch_weibo: bool=Option(False, '--weibo', '-w', help="Fetch weibo"), 
         fetch_relation: bool=Option(False, '--relation', '-r', help="Fetch relation"), 
         download_dir: str=Argument(config['download_dir'], help='Download directory')):
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
