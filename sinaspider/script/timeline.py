import select
import sys
from pathlib import Path

import pendulum
from typer import Option, Typer

from sinaspider import console
from sinaspider.helper import fetcher
from sinaspider.model import UserConfig
from sinaspider.page import SinaBot

from .helper import (
    default_path,
    logsaver_decorator,
    print_command, save_log,
    update_user_config
)

app = Typer()


class LogSaver:
    def __init__(self, command: str, download_dir: Path):
        self.command = command
        self.download_dir = download_dir
        self.save_log_at = pendulum.now()
        self.total_fetch_count = 0
        self.SAVE_LOG_INTERVAL = 12  # hours
        self.SAVE_LOG_FOR_COUNT = 100

    def save_log(self, fetch_count=0):
        self.total_fetch_count += fetch_count
        log_hours = self.save_log_at.diff().in_hours()
        console.log(
            f'total fetch count: {self.total_fetch_count}, '
            f'threshold: {self.SAVE_LOG_FOR_COUNT}')
        console.log(
            f'log hours: {log_hours}, threshold: {self.SAVE_LOG_INTERVAL}h')
        if (log_hours > self.SAVE_LOG_INTERVAL or
                self.total_fetch_count > self.SAVE_LOG_FOR_COUNT):
            console.log('Threshold reached, saving log automatically...')
        elif fetch_count == 0:
            console.log('Saving log manually...')
        else:
            return
        save_log(self.command, self.download_dir)
        self.save_log_at = pendulum.now()
        self.total_fetch_count = 0


@app.command()
@logsaver_decorator
def timeline(days: float = Option(...),
             frequency: float = 1,
             download_dir: Path = default_path):
    """
    Fetch timeline for users in database
    days: days to fetch
    frequency: hours between each fetching
    download_dir: image saving directory
    """
    query = (UserConfig.select()
             .where(UserConfig.weibo_fetch)
             .where(UserConfig.weibo_fetch_at.is_null(False))
             .where(UserConfig.weibo_next_fetch < pendulum.now())
             .where(~UserConfig.blocked)
             .order_by(UserConfig.weibo_fetch_at)
             )
    bot = SinaBot(art_login=False)
    bot_art = SinaBot(art_login=True)

    since = pendulum.now().subtract(days=days)

    WORKING_TIME = 0  # minutes
    logsaver = LogSaver('timeline', download_dir)
    while True:
        print_command()
        update_user_config()
        start_time = pendulum.now()
        start_count = fetcher.visits
        console.log(f'Fetching timeline since {since}...')

        bot_art.get_timeline(download_dir=download_dir, since=since,
                             friend_circle=False)
        bot.get_timeline(download_dir=download_dir,
                         since=since, friend_circle=True)
        since = start_time

        if start_time.diff().in_minutes() < WORKING_TIME:
            console.log('Looping user', style='red bold')
            for config in query.where(UserConfig.following)[:2]:
                config.fetch_weibo(download_dir/'Loop')
            for config in query.where(~UserConfig.following)[:1]:
                config.fetch_weibo(download_dir/'Loop')

            for config in (UserConfig.select()
                           .where(UserConfig.liked_fetch)
                           .where(UserConfig.liked_fetch_at.is_null(False))
                           .where(UserConfig.liked_next_fetch < pendulum.now())
                           .order_by(UserConfig.liked_fetch_at.asc())
                           )[:1]:
                console.log('Looping liked user', style='red bold')
                console.log(
                    f'latest liked fetch at {config.liked_fetch_at:%y-%m-%d}, '
                    f'next fetching time is {config.liked_next_fetch:%y-%m-%d}')
                config.fetch_liked(download_dir)

        while start_time.diff().in_minutes() < WORKING_TIME:
            if config := UserConfig.get_or_none(weibo_fetch=True,
                                                weibo_fetch_at=None):
                assert config.following
                config = config.from_id(config.user_id)
                config.fetch_weibo(download_dir)
            elif config := UserConfig.get_or_none(liked_fetch=True,
                                                  liked_fetch_at=None):
                config.fetch_liked(download_dir)
            else:
                break
        WORKING_TIME = 10
        logsaver.save_log(fetcher.visits - start_count)
        next_start_time = start_time.add(hours=frequency)
        console.rule(
            f'waiting for next fetching at {next_start_time:%H:%M:%S}',
            style='magenta on dark_magenta'
        )
        console.log(
            "Press S to fetching immediately,\n"
            "L to fetch log manually,\n"
            "Q to exit,\n"
            "int number for the time in minutes to fetch new users",
            style='info')
        while pendulum.now() < next_start_time:
            # sleeping for  600 seconds while listing for enter key
            if select.select([sys.stdin], [], [], 600)[0]:
                match (t := input().lower()):
                    case "s":
                        console.log(
                            "S key pressed. continuing immediately.")
                        WORKING_TIME = 0
                        break
                    case "q":
                        console.log("q pressed. exiting.")
                        return
                    case "l":
                        logsaver.save_log()
                        console.log(
                            f'latest start_time: {start_time:%y-%m-%d %H:%M:%S}')
                        console.log(
                            f'next_start_time: {next_start_time:%y-%m-%d %H:%M:%S}')
                        console.rule(
                            f'waiting for next fetching at {next_start_time:%H:%M:%S}',
                            style='magenta on dark_magenta'
                        )
                    case t if t.isdigit():
                        console.log(
                            "number detected,"
                            f"fetching new users for {t} minutes")
                        WORKING_TIME = int(t)
                        break
                    case _:
                        console.log(
                            "Press S to fetching immediately,\n"
                            "L to fetch log manually,\n"
                            "Q to exit,\n"
                            "int number for the time in minutes to fetch new users",
                            style='info'
                        )
                        continue


@app.command()
def write_meta(download_dir: Path = default_path):
    from imgmeta.script import rename, write_meta
    for folder in ['User', 'Timeline', 'Loop/Timeline']:
        ori = download_dir / folder
        if ori.exists():
            write_meta(ori)
            rename(ori, new_dir=True, root=ori.parent / (ori.stem + 'Pro'))
