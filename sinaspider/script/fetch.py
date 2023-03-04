from pathlib import Path
from time import sleep

import pendulum
from typer import Option, Typer

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.model import UserConfig

from .helper import default_path, logsaver, tidy_img, update_user_config

app = Typer()


# @app.command(help='Update users from timeline')
# @logsaver
# def timeline_(download_dir: Path = default_path,
#               days: float = None,
#               dry_run: bool = False):
#     since = pendulum.now().subtract(days=days)
#     get_timeline(download_dir, since, dry_run)
#     if not dry_run:
#         tidy_img(download_dir)


@app.command(help='Update users from timeline')
@logsaver
def timeline(days: float = Option(...),
             frequency: float = None,
             dry_run: bool = False,
             download_dir: Path = default_path):
    since = pendulum.now().subtract(days=days)
    next_fetching_time = pendulum.now()
    while True:
        while pendulum.now() < next_fetching_time:
            sleep(600)
        next_since = pendulum.now()
        update_user_config()
        get_timeline(download_dir, since, dry_run)
        if dry_run:
            return
        tidy_img(download_dir)
        if frequency is None:
            return
        # updat since
        since = next_since
        # wait for next fetching
        next_fetching_time = max(since.add(days=frequency), pendulum.now())
        console.log(f'next fetching time: {next_fetching_time}')


@app.command(help="Loop through users in database and fetch weibos")
@logsaver
def loop(new_user: bool = False, download_dir: Path = default_path):
    if new_user:
        users = (UserConfig.select()
                 .where(UserConfig.weibo_fetch)
                 .where(UserConfig.weibo_fetch_at.is_null()))
        uids = [uc.user_id for uc in users]
    else:
        users = (UserConfig.select()
                 .where(UserConfig.weibo_fetch)
                 .where(UserConfig.weibo_fetch_at.is_null(False))
                 .order_by(UserConfig.weibo_fetch_at))
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
    tidy_img(download_dir)


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
