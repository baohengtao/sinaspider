from pathlib import Path
import pendulum
from rich.prompt import Prompt, Confirm, IntPrompt
from sinaspider import console
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
        user_id = normalize_user_id(user_id)
        uc = UserConfig.from_id(user_id, save=False)
        if uc_in_db := UserConfig.get_or_none(user_id=user_id):
            console.log(f'用户{uc.username}已在列表中')
        uc.weibo_fetch = Confirm.ask(f"是否获取{uc.username}的微博？", default=True)
        if uc.weibo_fetch or uc_in_db:
            uc.save()
            console.log(f'用户{uc.username}更新完成')
        console.log(uc, '\n')
        if uc.weibo_fetch and Confirm.ask('是否现在抓取', default=False):
            start_page = IntPrompt.ask('start_page', default=1)
            uc.fetch_weibo(download_dir, start_page=start_page)


def get_loop(download_dir: Path = default_path, new_user_only: bool = False):

    users = UserConfig.select().order_by(UserConfig.weibo_update_at)
    if new_user_only:
        uids = [uc.user_id for uc in users if uc.weibo_update_at <
                pendulum.now().subtract(years=1)]
    else:
        uids = [uc.user_id for uc in users if uc.need_fetch]
    for uid in uids:
        uc = UserConfig.from_id(user_id=uid)
        uc.fetch_weibo(download_dir)


@app.command(help="Loop through users in database and fetch weibos")
def loop(download_dir: Path = default_path):
    get_loop(download_dir)


@app.command(help='Update users from timeline')
def timeline(download_dir: Path = default_path,
             days: float = None,
             dry_run: bool = False):
    since = pendulum.now().subtract(days=days)
    get_timeline(download_dir, since, dry_run)


@app.command(help="Fetch users' liked weibo")
def liked(download_dir: Path = default_path):
    for uc in UserConfig:
        if uc.liked_fetch and not uc.liked_last_id:
            uc.fetch_liked(download_dir)


def get_timeline(download_dir: Path,
                 since: pendulum.DateTime,
                 dry_run: bool = False):
    from sinaspider.page import Page
    for status in Page.timeline(since=since):
        uid = status['user']['id']
        if not (uc := UserConfig.get_or_none(user_id=uid)):
            continue
        created_at = pendulum.from_format(
            status['created_at'], 'ddd MMM DD HH:mm:ss ZZ YYYY')
        update_at = uc.weibo_update_at
        if uc.weibo_fetch and update_at < created_at:
            uc = UserConfig.from_id(uid)
            uc.fetch_weibo(download_dir)
            if dry_run:
                uc.weibo_update_at = update_at
                uc.save()
        if uc.liked_fetch and uc.liked_last_id:
            uc.fetch_liked(download_dir)


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
            get_timeline(download_dir, since)
            console.rule('[bold red]New users...', style="magenta")
            get_loop(download_dir, new_user_only=True)
            tidy_img(download_dir)
            # updat since
            since = next_since
            # wait for next fetching
            next_fetching_time = max(since.add(days=frequency), pendulum.now())
            console.log(f'next fetching time: {next_fetching_time}')
        except BaseException:
            with console.capture():
                console.print_exception(show_locals=True)
            raise
        finally:
            time_format = pendulum.now().format('YY-MM-DD_HHmmss')
            log_file = f"schedule_{time_format}.html"
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


def update_user_config():
    """
    Update photos num for user_config
    """
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
        weibo = Weibo.from_id(weibo_id, update=True)
        console.log(weibo)
        if medias := list(weibo.medias(download_dir)):
            console.log(
                f'Downloading {len(medias)} files to dir {download_dir}')
            download_files(medias)
