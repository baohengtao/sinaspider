
from pathlib import Path

import questionary
from rich.prompt import Confirm, Prompt
from typer import Typer

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.helper import normalize_user_id
from sinaspider.model import UserConfig

from .helper import default_path, logsaver, tidy_img

app = Typer()


@app.command(help='Add user to database of users whom we want to fetch from')
@logsaver
def user(download_dir: Path = default_path):
    """Add user to database of users whom we want to fetch from"""
    while user_id := Prompt.ask('请输入用户名:smile:'):
        if uc := UserConfig.get_or_none(username=user_id):
            user_id = uc.user_id
        try:
            user_id = normalize_user_id(user_id)
        except UserNotFoundError as e:
            console.log(e, style='error')
            continue
        if uc := UserConfig.get_or_none(user_id=user_id):
            console.log(f'用户{uc.username}已在列表中')
        uc = UserConfig.from_id(user_id)
        uc.weibo_fetch = Confirm.ask(f"是否获取{uc.username}的微博？", default=True)
        uc.save()
        console.log(uc, '\n')
        console.log(f'用户{uc.username}更新完成')
        if uc.weibo_fetch and not uc.following:
            console.log(f'用户{uc.username}未关注，记得关注🌸', style='notice')
        elif not uc.weibo_fetch and uc.following:
            console.log(f'用户{uc.username}已关注，记得取关🔥', style='notice')
        if not uc.weibo_fetch and Confirm.ask('是否删除该用户？', default=False):
            uc.delete_instance()
            console.log('用户已删除')
            if uc.following:
                console.log('记得取消关注', style='warning')
        elif uc.weibo_fetch and Confirm.ask('是否现在抓取', default=False):
            uc.fetch_weibo(download_dir)
            tidy_img(download_dir)


@app.command()
def artist():
    from sinaspider.model import Artist
    while username := Prompt.ask('请输入用户名:smile:'):
        if username.isdigit():
            artist = Artist.get_or_none(user_id=int(username))
        else:
            artist = (Artist.select().where(
                Artist.username == username).get_or_none())
        if not artist:
            console.log(f'用户 {username} 不在列表中')
            continue
        console.log(artist)
        if artist.folder == 'new':
            console.log('folder is new, skip')
            continue
        console.print(
            f"which folder ? current is [bold red]{artist.folder}[/bold red]")
        folder = questionary.select("choose folder:", choices=[
            'recent', 'super', 'no-folder']).unsafe_ask()
        if folder == 'no-folder':
            folder = None
        if artist.folder == folder:
            continue
        ques = f'change folder from {artist.folder} to {folder} ?'
        if questionary.confirm(ques).unsafe_ask():
            artist.folder = folder
            artist.save()
            console.print(
                f'{artist.username}: folder changed to [bold red]{folder}[/bold red]')


@app.command(help="Fetch users' liked weibo")
@logsaver
def liked_loop(download_dir: Path = default_path, max_user: int = 1):
    configs = (UserConfig.select()
               .where(UserConfig.liked_fetch)
               .where(UserConfig.liked_fetch_at.is_null(True))
               .limit(max_user))
    for config in configs:
        config.fetch_liked(download_dir)


@app.command(help="Config whether fetch user's liked weibo")
@logsaver
def liked(download_dir: Path = default_path):
    while user_id := Prompt.ask('请输入用户名:smile:'):
        if config := UserConfig.get_or_none(username=user_id):
            user_id = config.user_id
        else:
            user_id = normalize_user_id(user_id)
        if not UserConfig.get_or_none(user_id=user_id):
            console.log(f'用户{user_id}不在列表中')
            continue
        console.log(config, '\n')
        config.liked_fetch = Confirm.ask('是否获取该用户的点赞？', default=True)
        config.save()
        console.log(f'用户{config.username}更新完成')
        if config.liked_fetch and Confirm.ask('是否现在抓取', default=False):
            config.fetch_liked(download_dir)
