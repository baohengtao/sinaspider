from pathlib import Path

import pendulum
from rich.prompt import Prompt, Confirm, IntPrompt
from sinaspider import console, get_progress
from sinaspider.helper import (
    normalize_user_id,
    download_files,
    normalize_wb_id)
from sinaspider.model import UserConfig, Weibo
from typer import Typer
from time import sleep

app = Typer()
default_path = Path.home() / 'Pictures/Sinaspider'


@app.command(help='Add user to database of users whom we want to fetch from')
def user(download_dir: str = default_path):
    while user_id := Prompt.ask('请输入用户名:smile:'):
        if not (user_id := normalize_user_id(user_id)):
            continue
        uc = UserConfig.from_id(user_id, save=False)
        if uc_in_db := UserConfig.get_or_none(UserConfig.user_id == user_id):
            console.log(f'用户{uc.username}已在列表中')
        uc.weibo_fetch = Confirm.ask(f"是否获取{uc.username}的微博？", default=True)
        if uc.weibo_fetch or uc_in_db:
            uc.save()
            console.log(f'用户{uc.username}更新完成')
        console.log(uc, '\n')
        if uc.weibo_fetch and Confirm.ask('是否现在抓取', default=False):
            start_page = IntPrompt.ask('start_page', default=1)
            uc.fetch_weibo(download_dir, start_page=start_page)


@app.command(help="Continue fetch user weibos from certain page")
def user_continue(user: str, start_page: int,
                  download_dir: Path = default_path):
    user_id = normalize_user_id(user)
    if not user_id:
        console.log(f'{user} not exist', style='error')
        return
    uc = UserConfig.from_id(user_id)
    uc.weibo_update_at = pendulum.from_timestamp(0)
    uc.fetch_weibo(download_dir=download_dir, start_page=start_page)


@app.command(help="Loop through users in database and fetch weibos")
def loop(download_dir: Path = default_path, new_user_only: bool = False):
    import time
    users = UserConfig.select().order_by(UserConfig.weibo_update_at)
    if new_user_only:
        users = [uc for uc in users if uc.weibo_update_at <
                 pendulum.now().subtract(years=1)]
    else:
        users = [uc for uc in users if uc.need_fetch]
    with get_progress() as progress:
        for i, uc in progress.track(enumerate(users, start=1),
                                    total=len(users)):
            try:
                uc.fetch_weibo(download_dir)
                console.log(f'[yellow]第{i}个用户获取完毕')
            except KeyError:
                continue
            for flag in [20, 10, 5]:
                if i % flag == 0:
                    to_sleep = 3 * i
                    break
            else:
                to_sleep = 5
                time.sleep(5)
            console.log(f'sleep {to_sleep}...')
            time.sleep(to_sleep)


@app.command(help='Update users from timeline')
def timeline(download_dir: Path = default_path,
             since=None, days: float = None):
    from sinaspider.page import get_timeline_pages
    if since is None:
        since = pendulum.now().subtract(days=days)
    for status in get_timeline_pages(since=since):
        user = UserConfig.get_or_none(user_id=status['user']['id'])
        if not user:
            continue
        created_at = pendulum.parse(status['created_at'], strict=False)
        if user.weibo_fetch and user.weibo_update_at < created_at:
            user.fetch_weibo(download_dir)


@app.command(help='Schedule timeline command')
def schedule(download_dir: Path = default_path,
             days: float = None, frequency: float = 1):
    from rich.terminal_theme import MONOKAI
    since = pendulum.now().subtract(days=days)
    next_fetching_time = pendulum.now()
    while True:
        while pendulum.now() < next_fetching_time:
            sleep(600)
        try:
            next_since = pendulum.now()
            update_user_config()
            console.rule('[bold red]Timeline...', style="magenta")
            timeline(download_dir, since)
            console.rule('[bold red]New users...', style="magenta")
            loop(download_dir, new_user_only=True)
            tidy_img(download_dir)
            # updat since
            since = next_since
            # wait for next fetching
            next_fetching_time = max(since.add(days=frequency), pendulum.now())
            console.log(f'next fetching time: {next_fetching_time}')
        except:
            with console.capture():
                console.print_exception(show_locals=True)
            raise
        finally:
            log_file = f"sinaspider_{pendulum.now().format('YY-MM-DD_HHmmss')}.html"
            console.log(f'Saving log to {download_dir / log_file}')
            console.save_html(download_dir / log_file, theme=MONOKAI)


def tidy_img(download_dir):
    from imgmeta.script import write_meta, rename
    folders = ['Users', 'New']
    for folder in folders:
        ori = download_dir / folder
        if ori.exists():
            write_meta(ori)
            rename(ori, new_dir=True, root=ori.parent / (ori.stem + 'Pro'))


@app.command(help='Update photos num for user_config')
def update_user_config():
    from sinaspider.model import Artist
    for uc in UserConfig:
        if artist := Artist.get_or_none(user=uc.user):
            uc.photos_num = artist.photos_num
            uc.save()


@app.command(help="fetch weibo by weibo_id")
def weibo(download_dir: Path = default_path):
    while weibo_id := Prompt.ask('请输入微博ID:smile:'):
        if not (weibo_id := normalize_wb_id(weibo_id)):
            continue
        files = Weibo.from_id(weibo_id).medias(download_dir)
        download_files(files)


@app.command(help='save favorite')
def favorite(download_dir: Path = default_path):
    UserConfig.fetch_favorite(download_dir)
