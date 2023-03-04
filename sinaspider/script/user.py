from pathlib import Path

from rich.prompt import Confirm, Prompt
from typer import Typer

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.helper import normalize_user_id
from sinaspider.model import UserConfig

from .helper import default_path, logsaver, tidy_img

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
        uc.weibo_fetch = Confirm.ask(f"是否获取{uc.username}的微博？", default=True)
        uc.save()
        console.log(uc, '\n')
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
            tidy_img(download_dir)


@app.command(help="Loop through users in database and fetch weibos")
@logsaver
def user_loop(new_user: bool = False, download_dir: Path = default_path):
    if new_user:
        users = (UserConfig.select()
                 .where(UserConfig.weibo_fetch)
                 .where(UserConfig.weibo_fetch_at.is_null()))
        uids = [uc.user_id for uc in users]
    else:
        users = (UserConfig.select()
                 .where(UserConfig.weibo_fetch)
                 .where(UserConfig.weibo_fetch_at.is_null(False))
                 .order_by(UserConfig.weibo_fetch_at))
        uids = [uc.user_id for uc in users if uc.need_fetch]
    for uid in uids:
        try:
            config = UserConfig.from_id(user_id=uid)
        except UserNotFoundError:
            config: UserConfig = UserConfig.get(user_id=uid)
            console.log(
                f'用户 {config.username} 不存在 ({config.homepage})', style='error')
        else:
            config.fetch_weibo(download_dir)
    tidy_img(download_dir)
