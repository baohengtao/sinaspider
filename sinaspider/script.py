from pathlib import Path

from rich.prompt import Prompt, Confirm
from typer import Typer

from sinaspider import console
from sinaspider.helper import normalize_user_id
from sinaspider.model import UserConfig, User, Weibo, init_database

app = Typer()
default_path = Path.home() / 'Downloads/sinaspider_test'
init_database('sinaspider')


@app.command()
def user(download_dir: str = default_path):
    while user_id := Prompt.ask('请输入用户名:smile:'):
        if not (user_id := normalize_user_id(user_id)):
            continue
        user = User.from_id(user_id, update=True)
        if UserConfig.get_or_none(UserConfig.user_id == user.id):
            console.log(f'用户{user.screen_name}已在列表中')
            uc = UserConfig.from_id(user_id)
        elif not Confirm.ask("是否添加{user.screen_name}？"):
            continue
        else:
            uc = UserConfig.from_id(user_id)
            console.log(f'用户{user.screen_name}添加完成')
        console.log(uc, '\n')
        if Confirm.ask('是否现在抓取'):
            uc.fetch_weibo(download_dir)


@app.command()
def user_loop(download_dir: Path = default_path):
    query = UserConfig.select()
    total = query.count()
    for uc in query.order_by(UserConfig.weibo_update_at):
        uc.fetch_weibo(download_dir)


@app.command()
def weibo(download_dir: Path = default_path):
    from sinaspider.thread import download_files
    while weibo_id := Prompt.ask('请输入微博ID:smile:'):
        if not (weibo_id := normalize_user_id(weibo_id)):
            continue
        files = Weibo.from_id(weibo_id).medias(download_dir)
        download_files(files)


@app.command()
def weibo_continue(user: str, start_page: int, download_dir: Path = default_path):
    user_id = normalize_user_id(user)
    if not user_id:
        console.log(f'{user} not exist', style='error')
        return
    uc = UserConfig.from_id(user_id)
    uc.fetch_weibo(download_dir=download_dir, start_page=start_page)
