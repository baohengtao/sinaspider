from pathlib import Path

import pendulum
from rich.prompt import Confirm, Prompt
from typer import Typer

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.helper import normalize_user_id
from sinaspider.model import UserConfig

from .helper import default_path, logsaver

app = Typer()


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
        console.log(uc, '\n')
        uc.weibo_fetch = Confirm.ask(f"是否获取{uc.username}的微博？", default=True)
        uc.save()
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


@app.command(help="Loop through users in database and fetch weibos")
@logsaver
def user_loop(new_user: bool = False, download_dir: Path = default_path):
    if new_user:
        users = (UserConfig.select()
                 .where(UserConfig.weibo_fetch)
                 .where(UserConfig.weibo_fetch_at.is_null()))
    else:
        users = (UserConfig.select()
                 .where(UserConfig.weibo_fetch)
                 .where(UserConfig.weibo_fetch_at.is_null(False))
                 .order_by(UserConfig.weibo_fetch_at))
        users = [uc for uc in users if _need_fetch(uc)]
    for user in users:
        try:
            config = UserConfig.from_id(user_id=user.user_id)
        except UserNotFoundError:
            config = UserConfig.get(user_id=user.user_id)
            console.log(
                f'用户 {config.username} 不存在 ({config.homepage})', style='error')
        else:
            config.fetch_weibo(download_dir)


def _need_fetch(config: UserConfig) -> bool:
    if config.weibo_fetch_at < pendulum.now().subtract(months=3):
        return True
    elif config.weibo_fetch_at > pendulum.now().subtract(days=15):
        return False
    elif config.post_at is None:
        return False
    else:
        next_fetch = config.weibo_fetch_at - config.post_at + config.weibo_fetch_at
        return pendulum.now() > next_fetch
