import random
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
             liked_freq: float = 1,
             download_dir: Path = default_path):
    since = pendulum.now().subtract(days=days)
    next_fetching_time = pendulum.now()
    next_liked_fetching = pendulum.now().add(days=liked_freq)
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
        if next_liked_fetching < pendulum.now():
            liked_fetch = True
            next_liked_fetching = pendulum.now().add(days=liked_freq)
        else:
            liked_fetch = False

        _get_timeline(download_dir, since, liked_fetch)

        if frequency is None:
            return
        # update since
        since = next_since
        # wait for next fetching
        next_fetching_time = max(since.add(days=frequency), pendulum.now())


@logsaver
def _get_timeline(download_dir: Path,
                  since: pendulum.DateTime,
                  liked_fetch: bool
                  ):
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
            if uc.liked_fetch and uc.liked_fetch_at:
                random_days = 30 + random.random() * 180
                days = (pendulum.now() - uc.liked_fetch_at).in_days()
                if days > random_days:
                    uc.fetch_liked(download_dir)
    if liked_fetch:
        if config := UserConfig.get_or_none(
                liked_fetch=True, liked_fetch_at=None):
            config.fetch_liked(download_dir)


@app.command()
def write_meta(download_dir: Path = default_path):
    from imgmeta.script import rename, write_meta
    for folder in ['User', 'Timeline', 'Loop/User', 'Loop/Timeline']:
        ori = download_dir / folder
        if ori.exists():
            write_meta(ori)
            rename(ori, new_dir=True, root=ori.parent / (ori.stem + 'Pro'))
