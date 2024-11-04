import asyncio
import json
import sys
import time
from functools import wraps
from inspect import signature
from pathlib import Path

import pendulum
from rich.terminal_theme import MONOKAI

from sinaspider import console
from sinaspider.exceptions import DownloadFilesFailed
from sinaspider.helper import fetcher
from sinaspider.model import PG_BACK

if not (d := Path('/Volumes/Art')).exists():
    d = Path.home()/'Pictures'
default_path = d / 'Sinaspider'

pg_back = PG_BACK(default_path/'_pg_backup')


def print_command():
    argv = sys.argv
    argv[0] = Path(argv[0]).name
    console.log(
        f" run command  @ {pendulum.now().format('YYYY-MM-DD HH:mm:ss')}")
    console.log(' '.join(argv))


def logsaver_decorator(func):
    """Decorator to save console log to html file"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            try:
                return func(*args, **kwargs)
            except DownloadFilesFailed as e:
                filename = f'failed_imgs_{pendulum.now().strftime("%Y%m%d%H%M%S")}.json'
                json_file = default_path / filename
                console.log(
                    f'save failed imgs to {json_file}', style='error')
                json_file.write_text(json.dumps(
                    e.imgs, indent=4, ensure_ascii=False))
                raise e.errs[0]
        except Exception:
            with console.capture():
                console.print_exception(show_locals=True)
            raise
        finally:
            callargs = signature(func).bind(*args, **kwargs).arguments
            download_dir = callargs.get('download_dir', default_path)
            save_log(func.__name__, download_dir)

    return wrapper


def save_log(func_name, download_dir: Path):
    if not download_dir.exists():
        console.log(f'{download_dir} not exists...', style='error')
        download_dir = Path.home()/'Pictures'
    while True:
        time_format = pendulum.now().format('YY-MM-DD_HHmmss')
        log_file = f"{func_name}_{time_format}.html"
        log_path = download_dir / log_file
        if log_path.exists():
            time.sleep(1)
        else:
            break
    console.log(f'Saving log to {log_path}')

    console.save_html(log_path, theme=MONOKAI)
    fetcher.save_cookie()


class LogSaver:
    SAVE_LOG_FOR_COUNT = 200
    SAVE_LOG_INTERVAL = 24  # hours

    def __init__(self, command: str, download_dir: Path):
        self.command = command
        self.download_dir = download_dir
        self.save_log_at = pendulum.now()
        self.save_visits_at = fetcher.visits

    def save_log(self, save_manually=False, backup=True):
        if backup:
            pg_back.backup()
        fetch_count = fetcher.visits - self.save_visits_at
        log_hours = self.save_log_at.diff().in_hours()
        console.log(
            f'total fetch count: {fetch_count}, '
            f'threshold: {self.SAVE_LOG_FOR_COUNT}')
        console.log(
            f'log hours: {log_hours}, threshold: {self.SAVE_LOG_INTERVAL}h')
        if (log_hours > self.SAVE_LOG_INTERVAL or
                fetch_count > self.SAVE_LOG_FOR_COUNT):
            console.log('Threshold reached, saving log automatically...')
        elif save_manually:
            console.log('Saving log manually...')
        else:
            return
        save_log(self.command, self.download_dir)
        self.save_log_at = pendulum.now()
        self.save_visits_at = fetcher.visits


def run_async(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        async def coro_wrapper():
            return await func(*args, **kwargs)

        return asyncio.run(coro_wrapper())

    return wrapper
