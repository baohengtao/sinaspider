import select
import sys
from pathlib import Path

import pendulum
from typer import Option, Typer

from sinaspider import console
from sinaspider.model import UserConfig

from .helper import default_path, logsaver, update_user_config

app = Typer()


@app.command(help='Update users from timeline')
def timeline(days: float = Option(...),
             frequency: float = None,
             dry_run: bool = False,
             download_dir: Path = default_path):
    since = pendulum.now().subtract(days=days)
    next_fetching_time = pendulum.now()
    while True:
        while pendulum.now() < next_fetching_time:
            # sleeping for  600 seconds while listing for enter key
            if select.select([sys.stdin], [], [], 600)[0]:
                if input() == "":
                    console.log("Enter key pressed. continuing immediately.")
                    break
        console.log(f'Fetching timeline since {since}...')
        next_since = pendulum.now()
        update_user_config()
        _get_timeline(download_dir, since, dry_run)
        if dry_run or frequency is None:
            return
        # updat since
        since = next_since
        # wait for next fetching
        next_fetching_time = max(since.add(days=frequency), pendulum.now())


@logsaver
def _get_timeline(download_dir: Path,
                  since: pendulum.DateTime,
                  dry_run: bool = False):
    from sinaspider.page import Page
    if dry_run:
        download_dir /= 'dry_run'
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


@app.command()
def write_meta(download_dir: Path = default_path):
    from imgmeta.script import rename, write_meta
    for folder in ['User', 'Timeline']:
        ori = download_dir / folder
        if ori.exists():
            write_meta(ori)
            rename(ori, new_dir=True, root=ori.parent / (ori.stem + 'Pro'))


# @app.command(help='Update users from timeline')
# @logsaver
# def timeline_(download_dir: Path = default_path,
#               days: float = None,
#               dry_run: bool = False):
#     since = pendulum.now().subtract(days=days)
#     get_timeline(download_dir, since, dry_run)
#     if not dry_run:
#         tidy_img(download_dir)
