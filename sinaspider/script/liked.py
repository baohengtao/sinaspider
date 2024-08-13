
from pathlib import Path

import pendulum
from rich.prompt import Confirm, Prompt
from typer import Option, Typer

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.helper import normalize_user_id
from sinaspider.model import Friend, User, UserConfig

from .helper import default_path, logsaver_decorator, run_async

app = Typer()


@app.command(help="Config whether fetch user's liked weibo")
@logsaver_decorator
@run_async
async def liked(download_dir: Path = default_path):
    UserConfig.update_table()
    while user_id := Prompt.ask('请输入用户名:smile:'):
        if user := User.get_or_none(username=user_id):
            user_id = user.id
        else:
            user_id = await normalize_user_id(user_id)
        if not (config := UserConfig.get_or_none(user_id=user_id)):
            console.log(f'用户{user_id}不在列表中')
            continue
        console.log(config)
        config.liked_fetch = Confirm.ask('是否获取该用户的点赞？', default=True)
        config.save()
        console.log(f'✨ set liked_fetch to {config.liked_fetch}\n')
        if config.liked_fetch and Confirm.ask('是否现在抓取', default=False):
            await config.fetch_liked(download_dir)


@app.command(help="Fetch users' liked weibo")
@logsaver_decorator
@run_async
async def liked_loop(download_dir: Path = default_path,
                     max_user: int = 1,
                     fetching_duration: int = None,
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
                   .where(UserConfig.liked_fetch_at.is_null(False))
                   .where(UserConfig.liked_next_fetch < pendulum.now())
                   .order_by(UserConfig.liked_fetch_at.asc())
                   )
    if fetching_duration:
        max_user = None
        stop_time = pendulum.now().add(minutes=fetching_duration)
    else:
        stop_time = None
    console.log(f'Found {len(configs)} users to fetch liked weibo')
    for config in configs[:max_user]:
        config: UserConfig
        try:
            console.log(
                f'latest liked fetch at {config.liked_fetch_at:%y-%m-%d}, '
                f'next fetching time is {config.liked_next_fetch:%y-%m-%d}')
            await config.fetch_liked(download_dir)
        except UserNotFoundError:
            console.log(
                f'seems {config.username} deleted, disable liked_fetch',
                style='error')
            config.liked_fetch = False
            config.blocked = True
            config.save()
            console.log(config)
        if stop_time and stop_time < pendulum.now():
            console.log(f'stop since {fetching_duration} minutes passed')
            break


@app.command()
@logsaver_decorator
@run_async
async def friends(max_user: int = None):
    uids = {f.user_id for f in Friend}
    query = (UserConfig.select()
             .where(UserConfig.weibo_fetch)
             .where(UserConfig.weibo_fetch_at.is_null(False)))
    config: UserConfig
    for config in (query
                   .limit(max_user)
                   .where(UserConfig.user_id.not_in(uids))
                   ):
        # try:
        #     config = UserConfig.from_id(config.user_id)
        # except UserNotFoundError:
        #     pass
        await config.fetch_friends()
        console.log(config, '\n')
    for config in query:
        config.update_friends()
