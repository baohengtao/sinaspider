import sys
from functools import wraps
from inspect import getcallargs
from pathlib import Path
from time import sleep

import pendulum
import questionary
from rich.prompt import Confirm, Prompt
from rich.terminal_theme import MONOKAI
from typer import Typer

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.helper import (
    download_files,
    normalize_user_id,
    normalize_wb_id
)
from sinaspider.model import UserConfig, Weibo

app = Typer()
default_path = Path.home() / 'Pictures/Sinaspider'


def logsaver(func):
    """Decorator to save console log to html file"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        argv = sys.argv
        argv[0] = Path(argv[0]).name
        console.log(' '.join(argv))
        callargs = getcallargs(func, *args, **kwargs)
        try:
            return func(*args, **kwargs)
        except BaseException:
            with console.capture():
                console.print_exception(show_locals=True)
            raise
        finally:
            download_dir = callargs.get('download_dir', default_path)
            time_format = pendulum.now().format('YY-MM-DD_HHmmss')
            log_file = f"{func.__name__}_{time_format}.html"
            console.log(f'Saving log to {download_dir / log_file}')
            console.save_html(download_dir / log_file, theme=MONOKAI)

    return wrapper


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


def get_loop(download_dir: Path = default_path, new_user_only: bool = False):
    users = UserConfig.select().order_by(UserConfig.weibo_fetch_at)
    if new_user_only:
        uids = [uc.user_id for uc in users if uc.weibo_fetch_at <
                pendulum.now().subtract(years=1)]
    else:
        uids = [uc.user_id for uc in users if uc.need_fetch]
    for uid in uids:
        try:
            config = UserConfig.from_id(user_id=uid)
        except UserNotFoundError:
            config: UserConfig = UserConfig.get(user_id=uid)
            console.log(
                f'用户 {config.username} 不存在 ({config.homepage})', style='error')
        else:
            config.fetch_weibo(download_dir)


@app.command(help="Loop through users in database and fetch weibos")
@logsaver
def loop(download_dir: Path = default_path):
    get_loop(download_dir)
    tidy_img(download_dir)


@app.command(help='Update users from timeline')
@logsaver
def timeline(download_dir: Path = default_path,
             days: float = None,
             dry_run: bool = False):
    since = pendulum.now().subtract(days=days)
    get_timeline(download_dir, since, dry_run)
    if not dry_run:
        tidy_img(download_dir)


@app.command(help="Fetch users' liked weibo")
@logsaver
def liked(download_dir: Path = default_path, max_user: int = 1):
    configs = (UserConfig.select()
               .where(UserConfig.liked_fetch)
               .where(UserConfig.liked_fetch_at.is_null(True))
               .limit(max_user))
    for config in configs:
        config.fetch_liked(download_dir)
    while user_id := Prompt.ask('请输入用户名:smile:'):
        if config := UserConfig.get_or_none(username=user_id):
            user_id = config.user_id
        else:
            user_id = normalize_user_id(user_id)
        if not UserConfig.get_or_none(user_id=user_id):
            console.log(f'用户{user_id}不在列表中')
            continue
        config = UserConfig.from_id(user_id)
        config.liked_fetch = Confirm.ask('是否获取该用户的点赞？', default=True)
        config.save()
        console.log(config, '\n')
        console.log(f'用户{config.username}更新完成')
        if config.liked_fetch and Confirm.ask('是否现在抓取', default=False):
            config.fetch_liked(download_dir)


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
        fetch_at = uc.weibo_fetch_at
        if uc.weibo_fetch and fetch_at < created_at:
            uc = UserConfig.from_id(uid)
            uc.fetch_weibo(download_dir)
            if dry_run:
                uc.weibo_fetch_at = fetch_at
                uc.save()
        # if uc.liked_fetch and uc.liked_last_id:
        #     uc.fetch_liked(download_dir)


@app.command(help='Schedule timeline command')
@logsaver
def schedule(download_dir: Path = default_path,
             days: float = None, frequency: float = 1):
    since = pendulum.now().subtract(days=days)
    next_fetching_time = pendulum.now()
    while True:
        while pendulum.now() < next_fetching_time:
            sleep(600)
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


def tidy_img(download_dir: Path):
    from imgmeta.script import rename, write_meta
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


@app.command()
@logsaver
def weibo_update():
    from playhouse.shortcuts import update_model_from_dict

    from sinaspider.exceptions import WeiboNotFoundError
    from sinaspider.parser import WeiboParser
    for weibo in get_update():
        try:
            weibo_dict = WeiboParser(weibo.id).parse()
        except WeiboNotFoundError as e:
            weibo.username = weibo.user.username
            weibo.update_status = str(e)
            console.log(
                f"{weibo.username}({weibo.url}): :disappointed_relieved: {e}")
        else:
            update_model_from_dict(weibo, weibo_dict)
            weibo.username = weibo.user.username
            console.log(
                f"{weibo.username}({weibo.url}): :tada:  updated successfully!"
            )

        weibo.save()


def get_update():
    from sinaspider.page import Page
    recent_weibo = (Weibo.select()
                    .where(Weibo.update_status.is_null())
                    .where(Weibo.created_at > pendulum.now().subtract(months=6))
                    .order_by(Weibo.user_id.asc()))
    for i, weibo in enumerate(recent_weibo, start=1):
        if i % 20 == 0:
            console.log(f'✨ processing {i} / {len(recent_weibo)}')
        yield weibo
    console.log(':star2: Weibo in half year have been updated!')
    if not questionary.confirm('Continue?').unsafe_ask():
        return
    uid2visible: dict[int, bool] = {}
    for i, weibo in enumerate(process := Weibo.select()
                              .where(Weibo.update_status.is_null())
                              .order_by(Weibo.user_id.asc()), start=1):
        if i % 10 == 0:
            console.log(f'✨ processing {i} / {len(process)}')
        assert weibo.update_status is None
        assert weibo.created_at < pendulum.now().subtract(months=6)
        if (uid := weibo.user_id) not in uid2visible:
            uid2visible[uid] = (visible := Page(uid).get_visibility())
            if visible:
                if config := UserConfig.get_or_none(user_id=uid):
                    if not config.visible:
                        console.log(
                            f' {config.username}({uid}) is visible!', style='error')
        if not uid2visible[uid]:
            weibo.update_status = 'invisible'
            weibo.username = weibo.user.username
            console.log(
                f"{weibo.username}({weibo.url}): :disappointed_relieved: invisible")
            weibo.save()
        else:
            yield weibo
