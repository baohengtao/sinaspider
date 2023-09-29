
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
        console.log(config)
        config.liked_fetch = Confirm.ask('是否获取该用户的点赞？', default=True)
        config.save()
        console.log(f'✨ set liked_fetch to {config.liked_fetch}\n')
        if config.liked_fetch and Confirm.ask('是否现在抓取', default=False):
            config.fetch_liked(download_dir)


@app.command(help="Fetch users' liked weibo")
@logsaver
def liked_loop(download_dir: Path = default_path,
               max_user: int = 1,
               fetching_time: int = None,
               new_user: bool = Option(False, "--new-user", "-n")):
    if new_user:
        configs = (UserConfig.select()
                   .where(UserConfig.liked_fetch)
                   .where(UserConfig.liked_fetch_at.is_null(True))
                   .order_by(UserConfig.post_at.desc(nulls='last'))
                   )
    else:
        configs = (UserConfig.select()
                   .where(UserConfig.liked_fetch)
                   .order_by(UserConfig.liked_fetch_at.asc())
                   )
        configs = [c for c in configs if c.need_liked_fetch()]
    if fetching_time:
        max_user = None
        stop_time = pendulum.now().add(minutes=fetching_time)
    else:
        stop_time = None
    console.log(f'Found {len(configs)} users to fetch liked weibo')
    for config in configs[:max_user]:
        config.fetch_liked(download_dir)
        if stop_time and stop_time < pendulum.now():
            console.log(f'stop since {fetching_time} minutes passed')
            break


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
