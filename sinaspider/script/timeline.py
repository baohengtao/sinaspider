import select
import sys
from pathlib import Path

import pendulum
from typer import Option, Typer

from sinaspider import console
from sinaspider.model import UserConfig

from .helper import default_path, logsaver, update_user_config

app = Typer()


@app.command()
def timeline(days: float = Option(...),
             frequency: float = 6,
             download_dir: Path = default_path):
    """
    Fetch timeline for users in database

    days: days to fetch

    frequency: hours between each fetching

    download_dir: image saving directory
    """
    since = pendulum.now().subtract(days=days)
    fetching_time = pendulum.now()
    liked_fetch = False
    while True:
        while pendulum.now() < fetching_time:
            # sleeping for  600 seconds while listing for enter key
            if select.select([sys.stdin], [], [], 600)[0]:
                if input() == "":
                    console.log("Enter key pressed. continuing immediately.")
                    liked_fetch = False
                    break
        console.log(f'Fetching timeline since {since}...')
        next_since = pendulum.now()
        update_user_config()

        _get_timeline(download_dir, since, liked_fetch)

        # update since
        since = next_since
        # wait for next fetching
        fetching_time = next_since.add(hours=frequency)
        # always fetch liked after first update
        liked_fetch = True


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
            if uc.need_liked_fetch():
                uc.fetch_liked(download_dir)
    if liked_fetch:
        query = (UserConfig.select()
                 .where(UserConfig.liked_fetch)
                 .where(UserConfig.liked_fetch_at.is_null())
                 .order_by(UserConfig.post_at.desc(nulls='last'))
                 )
        if config := query.first():
            config.fetch_liked(download_dir)


@app.command()
def write_meta(download_dir: Path = default_path):
    from imgmeta.script import rename, write_meta
    for folder in ['User', 'Timeline', 'Loop/User', 'Loop/Timeline']:
        ori = download_dir / folder
        if ori.exists():
            write_meta(ori)
            rename(ori, new_dir=True, root=ori.parent / (ori.stem + 'Pro'))
