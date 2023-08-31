
from pathlib import Path

import pendulum
from rich.prompt import Confirm, Prompt
from typer import Option, Typer

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.helper import normalize_user_id
from sinaspider.model import Friend, UserConfig

from .helper import default_path, logsaver

app = Typer()


@app.command(help="Config whether fetch user's liked weibo")
@logsaver
def liked(download_dir: Path = default_path):
    while user_id := Prompt.ask('请输入用户名:smile:'):
        if config := UserConfig.get_or_none(username=user_id):
            user_id = config.user_id
        else:
            user_id = normalize_user_id(user_id)
        if not (config := UserConfig.get_or_none(user_id=user_id)):
            console.log(f'用户{user_id}不在列表中')
            continue
        console.log(config, '\n')
        config.liked_fetch = Confirm.ask('是否获取该用户的点赞？', default=True)
        config.save()
        console.log(f'用户{config.username}更新完成')
        if config.liked_fetch and Confirm.ask('是否现在抓取', default=False):
            config.fetch_liked(download_dir)


@app.command(help="Fetch users' liked weibo")
@logsaver
def liked_loop(download_dir: Path = default_path,
               max_user: int = 1,
               refresh: bool = Option(False, "--refresh", "-r")):
    if refresh:
        configs = (UserConfig.select()
                   .where(UserConfig.liked_fetch)
                   .where(UserConfig.liked_fetch_at
                          < pendulum.now().subtract(months=3))
                   .order_by(UserConfig.liked_fetch_at.asc())
                   .limit(max_user)
                   )
    else:
        configs = (UserConfig.select()
                   .where(UserConfig.liked_fetch)
                   .where(UserConfig.liked_fetch_at.is_null(True))
                   .limit(max_user))
    for config in configs:
        config.fetch_liked(download_dir)


@app.command()
@logsaver
def friends(max_user: int = None):
    uids = {f.user_id for f in Friend}
    for config in (UserConfig.select().limit(max_user)
                   .where(UserConfig.following)
                   .where(UserConfig.user_id.not_in(uids))
                   ):
        try:
            config = UserConfig.from_id(config.user_id)
        except UserNotFoundError:
            pass
        if config.following:
            console.log(config)
            config.fetch_friends()
