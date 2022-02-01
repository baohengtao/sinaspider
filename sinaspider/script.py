from pathlib import Path

import pendulum
from rich.prompt import Prompt, Confirm, IntPrompt
from typer import Typer

from sinaspider import console
from sinaspider.helper import normalize_user_id, download_files
from sinaspider.model import UserConfig, User, Weibo, init_database

app = Typer()
default_path = Path.home() / 'Downloads/sinaspider'
init_database('sinaspider')


@app.command(help='Add user to database of users whom we want to fetch from')
def user(download_dir: str = default_path):
    while user_id := Prompt.ask('请输入用户名:smile:'):
        if not (user_id := normalize_user_id(user_id)):
            continue
        User.from_id(user_id, update=True)
        uc = UserConfig.from_id(user_id, save=False)
        if uc_in_db := UserConfig.get_or_none(UserConfig.user_id == user_id):
            console.log(f'用户{uc.screen_name}已在列表中')
        uc.weibo_fetch = Confirm.ask(f"是否获取{uc.screen_name}的微博？")
        if uc.weibo_fetch or uc_in_db:
            uc.save()
            console.log(f'用户{uc.screen_name}更新完成')
        console.log(uc, '\n')
        if uc.weibo_fetch and Confirm.ask('是否现在抓取'):
            start_page = IntPrompt.ask('start_page', default=1)
            uc.fetch_weibo(download_dir, force_fetch=True, start_page=start_page)


@app.command(help="Continue fetch user weibos from certain page")
def user_continue(user: str, start_page: int, download_dir: Path = default_path):
    user_id = normalize_user_id(user)
    if not user_id:
        console.log(f'{user} not exist', style='error')
        return
    uc = UserConfig.from_id(user_id)
    uc.weibo_update_at = pendulum.from_timestamp(0)
    uc.fetch_weibo(download_dir=download_dir, start_page=start_page)


@app.command(help="Loop through users in database and fetch weibos")
def user_loop(download_dir: Path = default_path):
    query = UserConfig.select()
    for uc in query.order_by(UserConfig.weibo_update_at):
        uc.fetch_weibo(download_dir)


@app.command(help="fetch weibo by weibo_id")
def weibo(download_dir: Path = default_path):
    while weibo_id := Prompt.ask('请输入微博ID:smile:'):
        if not (weibo_id := normalize_user_id(weibo_id)):
            continue
        files = Weibo.from_id(weibo_id).medias(download_dir)
        download_files(files)
