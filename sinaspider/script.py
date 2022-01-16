from pathlib import Path

import typer
from requests.exceptions import ProxyError, SSLError, ConnectionError
from sqlmodel import Session, select
from typer import Typer

from sinaspider.method import UserConfigMethod, UserMethod, WeiboMethod
from sinaspider.model import UserConfig, engine
from sinaspider.util.helper import logger, get_url

app = Typer()
default_path = Path.home() / 'Downloads/sinaspider_test'

def _parse_users(users:str):
    users = [u for u in users.split() if u]
    for user_id in users:
        if not user_id.isdigit():
            r = get_url(f'https://m.weibo.cn/n/{user_id}')
            user_id = r.url.split('/')[-1]
        yield int(user_id)


@app.command()
def add(users: str):
    session = Session(engine)
    users = list(_parse_users(users))

    for user_id in users:
        UserMethod.from_id(user_id, session, update=True)
        UserConfigMethod(user_id, session=session)


@app.command()
def save(weibo_id):
    from sinaspider.util.thread import ClosableQueue, start_threads, stop_threads
    session = Session(engine)
    weibo = WeiboMethod.from_id(weibo_id, session)
    medias = WeiboMethod(weibo).medias(default_path)
    img_queue = ClosableQueue(maxsize=10)
    threads = start_threads(5, img_queue)
    for img in medias:
        img_queue.put(img)
    stop_threads(img_queue, threads)
    return





@app.command()
def weibo(users: str = '',start_page: int = 1,
          download_dir: Path = default_path):

    session = Session(engine)
    users = list(_parse_users(users))
    for user_id in users:
        UserMethod.from_id(user_id, session, update=True)
        UserConfigMethod(int(user_id), session=session).fetch_weibo(download_dir, update=True, start_page=start_page)

    if users:
        raise typer.Exit()

    for uc in session.exec(select(UserConfig)):
        print(uc)
        while True:
            try:
                if artist := uc.user.artist:
                    num=artist[0].recent_num
                    update_interval = min(180/(num+1), 20)
                else:
                    update_interval = 20

                    
                # update_interval = min(1000 / uc.user.artist[0].photos_num, 20)
                UserConfigMethod(uc.id, session=session).fetch_weibo(
                    download_dir, update=True,
                    update_interval=update_interval)
                break
            except (ProxyError, SSLError, ConnectionError):
                logger.warning('Internet seems broken, sleeping...')
                for i in range(600):
                    print(f'sleeping {600 - i - 1}', end='\r')
                continue


@app.command()
def collection(download_dir: Path = default_path):
    session = Session(engine)
    uc = session.exec(select(UserConfig)).first()
    UserConfigMethod(uc.id, session=session).fetch_collections(download_dir / 'collections')


@app.command()
def relation():
    session = Session(engine)
    for uc in session.exec(select(UserConfig)):
        while True:
            try:
                uc = UserConfigMethod(uc.id, session=session)
                if uc.user_config.relation_fetch:
                    print(uc.user_config)
                    uc.fetch_friends()
                break
            except (ProxyError, SSLError, ConnectionError):
                logger.warning('Internet seems broken, sleeping...')
                for i in range(600):
                    print(f'sleeping {600 - i - 1}', end='\r')
                continue
