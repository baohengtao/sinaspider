
from pathlib import Path

from rich.prompt import Confirm, Prompt
from typer import Typer

from sinaspider import console
from sinaspider.helper import normalize_user_id
from sinaspider.model import UserConfig

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
        if not UserConfig.get_or_none(user_id=user_id):
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
def liked_loop(download_dir: Path = default_path, max_user: int = 1):
    configs = (UserConfig.select()
               .where(UserConfig.liked_fetch)
               .where(UserConfig.liked_fetch_at.is_null(True))
               .limit(max_user))
    for config in configs:
        config.fetch_liked(download_dir)
