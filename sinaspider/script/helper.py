import sys
from functools import wraps
from inspect import signature
from pathlib import Path

import pendulum
from imgmeta.script import write_meta
from rich.terminal_theme import MONOKAI

from sinaspider import console

default_path = Path.home() / 'Pictures/Sinaspider'


def logsaver(func):
    """Decorator to save console log to html file"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        argv = sys.argv
        argv[0] = Path(argv[0]).name
        console.log(
            f" run command  @ {pendulum.now().format('YYYY-MM-DD HH:mm:ss')}")
        console.log(' '.join(argv))
        callargs = signature(func).bind(*args, **kwargs).arguments
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
            for folder in ['Users', 'New']:
                ori = download_dir / folder
                if ori.exists():
                    write_meta(ori)

    return wrapper


def update_user_config():
    """
    Update photos num for user_config
    """
    from sinaspider.model import Artist, UserConfig
    for uc in UserConfig:
        if artist := Artist.get_or_none(user=uc.user):
            uc.photos_num = artist.photos_num
            uc.save()
