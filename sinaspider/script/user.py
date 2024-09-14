from pathlib import Path

import pendulum
from peewee import fn
from rich.prompt import Confirm, Prompt
from typer import Option, Typer

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.helper import fetcher, normalize_user_id
from sinaspider.model import UserConfig
from sinaspider.page import SinaBot
from sinaspider.script.helper import LogSaver

from .helper import default_path, logsaver_decorator, run_async

app = Typer()


@app.command(help='Add user to database of users whom we want to fetch from')
@logsaver_decorator
@run_async
async def user(download_dir: Path = default_path):
    """Add user to database of users whom we want to fetch from"""
    while user_id := Prompt.ask('请输入用户名:smile:').strip():
        if uc := UserConfig.get_or_none(username=user_id):
            user_id = uc.user_id
        try:
            user_id = await normalize_user_id(user_id)
        except UserNotFoundError as e:
            console.log(e, style='error')
            continue
        if uc := UserConfig.get_or_none(user_id=user_id):
            console.log(f'用户{uc.username}已在列表中')
        uc = await UserConfig.from_id(user_id)
        console.log(uc, '\n')
        uc.weibo_fetch = Confirm.ask(
            f"是否获取{uc.username}的微博？", default=bool(uc.weibo_fetch_at))
        if not uc.weibo_fetch:
            if uc.weibo_fetch_at is None and uc.following:
                uc.weibo_fetch = None
                console.log(
                    f'set {uc.username} weibo_fetch to None '
                    'since it not fetched yet', style='notice')
        uc.save()
        console.log(f'用户{uc.username}更新完成')
        if uc.weibo_fetch and not uc.following:
            console.log(f'用户{uc.username}未关注，记得关注🌸', style='notice')
        elif uc.weibo_fetch is False and uc.following:
            console.log(f'用户{uc.username}已关注，记得取关🔥', style='notice')
        if uc.weibo_fetch is False and Confirm.ask('是否删除该用户？', default=False):
            uc.delete_instance()
            console.log('用户已删除')
            if uc.following:
                console.log('记得取消关注', style='warning')
        elif uc.weibo_fetch is not False and Confirm.ask(
                '是否现在抓取', default=(uc.weibo_fetch is None)):
            await uc.fetch_weibo(download_dir)


@app.command()
@logsaver_decorator
@run_async
async def user_add(max_user: int = 20,
                   all_user: bool = Option(False, '--all-user', '-a'),
                   download_dir: Path = default_path):
    if all_user:
        max_user = None
    UserConfig.update_table()
    bot = await SinaBot.create(art_login=True)
    uids = {u.user_id for u in UserConfig.select().where(UserConfig.following)}
    uids_following = [u['id'] async for u in bot
                      .get_following_list(max_user=max_user)]
    to_add = [uid for uid in uids_following if uid not in uids]
    if max_user is None:
        if uids := uids - set(uids_following):
            raise ValueError(f'there are uids {uids} not in following list')
    console.log(f'{len(to_add)} users will be added')
    for u in to_add[::-1]:
        console.log(f'adding {u} to UserConfig...')
        console.log(await UserConfig.from_id(u), '\n')

    special_fol = {u['id']: u['remark'] async for u in bot.get_following_list(
        special_following=True)}
    for u in UserConfig:
        if remark := special_fol.get(u.user_id):
            if u.username != remark:
                u = await UserConfig.from_id(u.user_id)
        if u.following and not u.photos_num:
            if u.user_id not in special_fol:
                console.log(f'adding {u.username} ({u.homepage}) '
                            'to special following list...')
                await bot.set_special_follow(u.user_id, True)
        elif u.user_id in special_fol:
            console.log(f'removing {u.username} ({u.homepage}) '
                        'from special following list...')
            await bot.set_special_follow(u.user_id, False)

    await fetcher.toggle_art(True)
    nov = [u for u in UserConfig.select()
           .where(UserConfig.weibo_cache_at.is_null())
           .where(UserConfig.weibo_fetch_at.is_null())
           if u.visible is not True and not (await u.set_visibility())]

    to_cache = []
    for u in nov:

        if not Confirm.ask(
                f'{u.username} only 180 days visible, '
                'caching now?', default=True):
            continue
        to_cache.append(u)
        console.log(u, '\n')

    for u in to_cache:
        await u.fetch_weibo(download_dir)


@app.command(help="Loop through users in database and fetch weibos")
@logsaver_decorator
@run_async
async def user_loop(download_dir: Path = default_path,
                    max_user: int = 1,
                    fetching_duration: int = None,
                    new_user: bool = Option(False, "--new-user", "-n"),
                    following: bool = Option(False, "--following", "-f")):
    UserConfig.update_table()
    logsaver = LogSaver('user_loop', download_dir)
    query = (UserConfig.select()
             .where(UserConfig.weibo_fetch | UserConfig.weibo_fetch.is_null())
             .where(UserConfig.weibo_fetch_at.is_null(False)
                    | UserConfig.weibo_cache_at.is_null(False))
             .where(~UserConfig.blocked)
             .order_by(UserConfig.following | UserConfig.is_friend,
                       fn.COALESCE(UserConfig.weibo_fetch_at,
                                   UserConfig.weibo_cache_at),
                       UserConfig.id)
             )

    cond1 = (UserConfig.weibo_fetch & UserConfig.weibo_fetch_at.is_null())
    cond2 = (UserConfig.weibo_fetch.is_null() &
             UserConfig.weibo_cache_at.is_null())
    query_new = (UserConfig.select()
                 .where(cond1 | cond2))

    assert not query_new.where(~UserConfig.following)
    if new_user:
        users = query_new.where(UserConfig.following)
        console.log(f'{len(users)} users has been found')
        if not fetching_duration:
            users = users[:max_user]
            console.log(f'{len(users)} users will be fetched')

    else:
        if following:
            users = query.where(UserConfig.following | UserConfig.is_friend)
        else:
            users = query.where(~UserConfig.following & ~UserConfig.is_friend)
        if x := users.where(UserConfig.weibo_next_fetch < pendulum.now()):
            users = x
        else:
            users = users[:max_user]
        download_dir /= 'Loop'
        console.log(f'{len(users)} will be fetched...')
    if fetching_duration:
        stop_time = pendulum.now().add(minutes=fetching_duration)
    else:
        stop_time = None
    for i, user in enumerate(users, start=1):
        try:
            config = await UserConfig.from_id(user_id=user.user_id)
        except UserNotFoundError:
            config = UserConfig.get(user_id=user.user_id)
            config.blocked = True
            config.save()
            console.log(
                f'用户 {config.username} 不存在 ({config.homepage})', style='error')
        else:
            await config.fetch_weibo(download_dir)
        console.log(f'user {i}/{len(users)} completed!')
        if new_user:
            logsaver.save_log(save_manually=True, backup=False)
        if stop_time and stop_time < pendulum.now():
            console.log(f'stop since {fetching_duration} minutes passed')
            break
