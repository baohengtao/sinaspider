import select
import sys
import time
from pathlib import Path

import pendulum
from typer import Option, Typer

from sinaspider import console
from sinaspider.model import UserConfig
from sinaspider.page import SinaBot

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
    from .liked import liked_loop
    from .user import user_loop
    bot = SinaBot(art_login=False)
    bot_art = SinaBot(art_login=True)

    since = pendulum.now().subtract(days=days)
    fetching_time = pendulum.now()
    fetching_duration = 0
    while True:
        while pendulum.now() < fetching_time:
            # sleeping for  600 seconds while listing for enter key
            if select.select([sys.stdin], [], [], 600)[0]:
                match (t := input()):
                    case "":
                        console.log(
                            "Enter key pressed. continuing immediately.")
                        fetching_duration = 0
                        break
                    case "q":
                        console.log("q pressed. exiting.")
                        return
                    case t if t.isdigit():
                        console.log(
                            "number detected,"
                            f"fetching new users for {t} minutes")
                        fetching_duration = int(t)
                        break
                    case _:
                        console.log(
                            "Press enter to fetching immediately,\n"
                            "Q to exit,\n"
                            "int number for the time in minutes to fetch new users")
                        continue

        console.log(f'Fetching timeline since {since}...')
        next_since = pendulum.now()
        update_user_config()

        _get_timeline(bot_art, download_dir, since, friend_circle=False)
        _get_timeline(bot, download_dir, since, friend_circle=True)
        if fetching_duration > 0:
            fetch_until = time.time() + fetching_duration * 60
            if UserConfig.get_or_none(weibo_fetch=True, weibo_fetch_at=None):
                user_loop(download_dir=download_dir,
                          new_user=True, fetching_duration=fetching_duration)
                console.log()
            if (remain := fetch_until - time.time()) > 0:
                if UserConfig.get_or_none(
                        liked_fetch=True, liked_fetch_at=None):
                    liked_loop(download_dir=download_dir,
                               new_user=True, fetching_duration=remain/60)

        # update since
        since = next_since
        # wait for next fetching
        fetching_time = next_since.add(hours=frequency)
        # always fetch new user for 1 hour after first update
        fetching_duration = 60
        console.log(f'waiting for next fetching at {fetching_time:%H:%M:%S}')


@logsaver
def _get_timeline(bot: SinaBot, download_dir: Path,
                  since: pendulum.DateTime,
                  friend_circle=False
                  ):
    bot.get_timeline(download_dir=download_dir, since=since,
                     friend_circle=friend_circle)


@app.command()
def write_meta(download_dir: Path = default_path):
    from imgmeta.script import rename, write_meta
    for folder in ['User', 'Timeline', 'Loop/Timeline']:
        ori = download_dir / folder
        if ori.exists():
            write_meta(ori)
            rename(ori, new_dir=True, root=ori.parent / (ori.stem + 'Pro'))
