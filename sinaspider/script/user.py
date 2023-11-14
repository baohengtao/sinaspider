from pathlib import Path

import pendulum
from rich.prompt import Confirm, Prompt
from typer import Option, Typer

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.helper import fetcher, normalize_user_id
from sinaspider.model import UserConfig
from sinaspider.page import SinaBot

from .helper import default_path, logsaver_decorator, update_user_config

app = Typer()


@app.command(help='Add user to database of users whom we want to fetch from')
@logsaver_decorator
def user(download_dir: Path = default_path):
    """Add user to database of users whom we want to fetch from"""
    while user_id := Prompt.ask('请输入用户名:smile:').strip():
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


@app.command()
@logsaver_decorator
def user_add(max_user: int = 20,
             all_user: bool = Option(False, '--all-user', '-a'),
             download_dir: Path = default_path):
    from itertools import islice
    if all_user:
        max_user = None
    update_user_config()
    bot = SinaBot(art_login=True)
    uids = {u.user_id for u in UserConfig.select().where(UserConfig.following)}
    uids_following = [u['id'] for u in islice(bot.get_following_list(),
                                              max_user)]
    to_add = [uid for uid in uids_following if uid not in uids]
    if max_user is None:
        if uids := uids - set(uids_following):
            raise ValueError(f'there are uids {uids} not in following list')
    console.log(f'{len(to_add)} users will be added')
    for u in to_add[::-1]:
        console.log(f'adding {u} to UserConfig...')
        console.log(UserConfig.from_id(u), '\n')

    special_fol = {u['id']: u['remark'] for u in bot.get_following_list(
        special_following=True)}
    for u in UserConfig:
        if remark := special_fol.get(u.user_id):
            if u.username != remark:
                u = UserConfig.from_id(u.user_id)
        if u.following and not u.photos_num:
            if u.user_id not in special_fol:
                console.log(f'adding {u.username}({u.homepage}) '
                            'to special following list...')
                bot.set_special_follow(u.user_id, True)
        elif u.user_id in special_fol:
            console.log(f'removing {u.username}({u.homepage}) '
                        'from special following list...')
            bot.set_special_follow(u.user_id, False)

    fetcher.toggle_art(True)
    nov = [u for u in UserConfig if u.weibo_fetch_at is None
           and u.visible is not True and not u.set_visibility()]
    for u in nov:
        if u.weibo_fetch is False:
            if not Confirm.ask(
                    f'{u.username} only 180 days visible, '
                    'set weibo_fetch to True?', default=True):
                continue
        u.weibo_fetch = True
        u.save()
        console.log(u)
    nov = [u for u in nov if u.weibo_fetch]
    if nov and Confirm.ask('fetching now ?', default=True):
        for u in nov:
            if u.weibo_fetch:
                u.fetch_weibo(download_dir)


@app.command(help="Loop through users in database and fetch weibos")
@logsaver_decorator
def user_loop(download_dir: Path = default_path,
              max_user: int = 1,
              fetching_duration: int = None,
              new_user: bool = Option(False, "--new-user", "-n"),
              following: bool = Option(False, "--following", "-f")):
    if new_user:
        users = (UserConfig.select()
                 .where(UserConfig.weibo_fetch)
                 .where(UserConfig.weibo_fetch_at.is_null()))
        assert not users.where(~UserConfig.following)
        users = users.where(UserConfig.following)
        console.log(f'{len(users)} users has been found')
        if not fetching_duration:
            users = users[:max_user]
            console.log(f'{len(users)} users will be fetched')

    else:
        users = (UserConfig.select()
                 .where(UserConfig.weibo_fetch)
                 .where(UserConfig.weibo_fetch_at.is_null(False))
                 .where(~UserConfig.blocked)
                 .order_by(UserConfig.following, UserConfig.weibo_fetch_at)
                 )
        if following:
            users = users.where(UserConfig.following | UserConfig.is_friend)
        else:
            users = users.where(~UserConfig.following & ~UserConfig.is_friend)
        users = [uc for uc in users if pendulum.now() > uc.next_weibo_fetch]
        download_dir /= 'Loop'
        console.log(f'{len(users)} will be fetched...')
    if fetching_duration:
        stop_time = pendulum.now().add(minutes=fetching_duration)
    else:
        stop_time = None
    for i, user in enumerate(users, start=1):
        try:
            config = UserConfig.from_id(user_id=user.user_id)
        except UserNotFoundError:
            config = UserConfig.get(user_id=user.user_id)
            config.blocked = True
            config.save()
            console.log(
                f'用户 {config.username} 不存在 ({config.homepage})', style='error')
        else:
            config.fetch_weibo(download_dir)
        console.log(f'user {i}/{len(users)} completed!')
        if stop_time and stop_time < pendulum.now():
            console.log(f'stop since {fetching_duration} minutes passed')
            break
