from typer import Typer

from sinaspider.helper import normalize_user_id
from sinaspider.model import UserConfig, User
from loguru import logger
from pathlib import Path

app = Typer()
default_path = Path.home() / 'Downloads/sinaspider_test'

@app.command()
def add(users: str):
    for user_id in users.split():
        if not (user_id := normalize_user_id(user_id)):
            continue
        User.from_id(user_id, update=True)
        uc = UserConfig.from_id(user_id)

def weibo_continue(user:str,  start_page:int, download_dir:Path=default_path):
    user_id = normalize_user_id(user)
    if not user_id:
        logger.error(f'{user} not exist')
        return
    uc = UserConfig.from_id(user_id)
    uc.fetch_weibo(download_dir=download_dir, start_page=start_page)

def weibo(download_dir:Path=default_path):
    for uc in UserConfig.select():
        print(uc)
        update_interval=10
        uc.fetch_weibo(download_dir, update=True, update_interval=update_interval)



