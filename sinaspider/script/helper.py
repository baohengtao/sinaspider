import sys
from functools import wraps
from inspect import signature
from pathlib import Path

import pendulum
from rich.terminal_theme import MONOKAI

from sinaspider import console

if not (d := Path('/Volumes/Art')).exists():
    d = Path.home()/'Pictures'
default_path = d / 'Sinaspider'


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
            return func(*args, **kwargs)
        except Exception:
            with console.capture():
                console.print_exception(show_locals=True)
            raise
        finally:
            callargs = signature(func).bind(*args, **kwargs).arguments
            download_dir = callargs.get('download_dir', default_path)
            save_log(func.__name__, download_dir)

    return wrapper


def save_log(func_name, download_dir):
    time_format = pendulum.now().format('YY-MM-DD_HHmmss')
    log_file = f"{func_name}_{time_format}.html"
    console.log(f'Saving log to {download_dir / log_file}')
    console.save_html(download_dir / log_file, theme=MONOKAI)


def update_user_config():
    """
    Update photos num for user_config
    """
    from photosinfo.model import Girl

    from sinaspider.model import UserConfig
    for uc in UserConfig:
        uc: UserConfig
        uc.username = uc.user.username
        if girl := Girl.get_or_none(sina_id=uc.user_id):
            uc.photos_num = girl.total_num
            uc.folder = girl.folder
        else:
            uc.photos_num = 0
        uc.weibo_next_fetch = uc.get_weibo_next_fetch()
        uc.liked_next_fetch = uc.get_liked_next_fetch()
        uc.save()
