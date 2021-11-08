from pathlib import Path
from typing import Optional

import typer
from requests.exceptions import ProxyError, SSLError, ConnectionError
from sqlmodel import Session, select
from typer import Typer

from sinaspider.method import UserConfigMethod
from sinaspider.model import UserConfig, engine
from sinaspider.util.helper import logger

app = Typer()


@app.command()
def weibo(download_dir: Path = Path.home() / 'Downloads/sinaspider_test',
          users: Optional[list[int]] = typer.Option(None),
          dry_run=typer.Option(False, "--dry-run")):
    session = Session(engine)
    for user in users:
        UserConfigMethod(user, session=session).fetch_weibo(download_dir, update=dry_run)

    for uc in session.exec(select(UserConfig)):
        print(uc)
        while True:
            try:
                update_interval = min(3000 / uc.user.statuses_count, 10)
                UserConfigMethod(uc.id, session=session).fetch_weibo(
                    download_dir, update=dry_run, 
                    update_interval=update_interval)
                break
            except (ProxyError, SSLError, ConnectionError):
                logger.warning('Internet seems broken, sleeping...')
                for i in range(600):
                    print(f'sleeping {600 - i - 1}', end='\r')
                continue


@app.command()
def relation():
    session = Session(engine)
    for uc in session.exec(select(UserConfig)):
        while True:
            try:
                UserConfigMethod(uc.id, session=session).fetch_friends()
                break
            except (ProxyError, SSLError, ConnectionError):
                logger.warning('Internet seems broken, sleeping...')
                for i in range(600):
                    print(f'sleeping {600 - i - 1}', end='\r')
                continue
