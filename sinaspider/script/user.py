import itertools
from pathlib import Path

import pendulum
from rich.prompt import Confirm, Prompt
from typer import Option, Typer

from sinaspider import console
from sinaspider.exceptions import UserNotFoundError
from sinaspider.helper import fetcher, normalize_user_id
from sinaspider.model import UserConfig, WeiboCache
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
        if config := UserConfig.get_or_none(username=user_id):
            user_id = config.user_id
        try:
            user_id = await normalize_user_id(user_id)
        except UserNotFoundError as e:
            console.log(e, style='error')
            continue
        if config := UserConfig.get_or_none(user_id=user_id):
            console.log(f'用户{config.username}已在列表中')
        config = await UserConfig.from_id(user_id)
        console.log(config, '\n')
        config.weibo_fetch = Confirm.ask(
            f"是否获取{config.username}的微博？", default=config.weibo_fetch)
        if config.weibo_fetch and config.is_caching:
            if not Confirm.ask(
                    "current is caching, keep caching?", default=True):
                config.weibo_fetch_at = None
                config.is_caching = False
        config.save()
        console.log(f'用户{config.username}更新完成')
        if config.weibo_fetch and not config.following:
            console.log(f'用户{config.username}未关注，记得关注🌸', style='notice')
        elif not config.weibo_fetch and config.following:
            console.log(f'用户{config.username}已关注，记得取关🔥', style='notice')
        if config.weibo_fetch is False and Confirm.ask('是否删除该用户？', default=False):
            u = config.user
            for n in itertools.chain(u.weibos, u.config, u.artist):
                console.log(n, '\n')
            if Confirm.ask(f'是否删除{u.username}({u.id})？', default=False):
                for n in itertools.chain(u.weibos, u.config, u.artist, u.friends,
                                         u.weibos_liked, u.weibos_missed):
                    n.delete_instance()
                u.delete_instance()
            if caches := WeiboCache.select().where(WeiboCache.user_id == u.id):
                if Confirm.ask(f'find {len(caches)} weibo caches, delete?'):
                    for cache in caches:
                        cache.delete_instance()
            console.log('用户已删除')
            if config.following:
                console.log('记得取消关注', style='warning')
        elif config.weibo_fetch and Confirm.ask('是否现在抓取', default=False):
            await config.fetch_weibo(download_dir)


@app.command()
@logsaver_decorator
@run_async
async def user_add(max_user: int = 20,
                   all_user: bool = Option(False, '--all-user', '-a')):
    max_user: int | None = None if all_user else max_user
    await UserConfig.update_table()
    bot_art = await SinaBot.create(art_login=True)
    uids = {u.user_id for u in UserConfig.select().where(UserConfig.following)}
    uids_following = [u['id'] async for u in bot_art
                      .get_following_list(max_user=max_user)]
    to_add = [uid for uid in uids_following if uid not in uids]
    if max_user is None:
        for u in uids - set(uids_following):
            try:
                await UserConfig.from_id(u)
            except UserNotFoundError:
                console.log(UserConfig.get(user_id=u))
                console.log('user not exist\n', style='error')
    console.log(f'{len(to_add)} users will be added')
    for u in to_add[::-1]:
        console.log(f'adding {u} to UserConfig...')
        console.log(await UserConfig.from_id(u), '\n')

    special_fol = {u['id']: u['remark'] async for u in bot_art.get_following_list(
        special_following=True)}
    for u in UserConfig:
        if remark := special_fol.get(u.user_id):
            if u.username != remark:
                u = await UserConfig.from_id(u.user_id)
        if u.following and not u.photos_num:
            if u.user_id not in special_fol:
                console.log(f'adding {u.username} ({u.homepage}) '
                            'to special following list...')
                await bot_art.set_special_follow(u.user_id, True)
        elif u.user_id in special_fol:
            console.log(f'removing {u.username} ({u.homepage}) '
                        'from special following list...')
            await bot_art.set_special_follow(u.user_id, False)
    if not all_user:
        return
    bot = await SinaBot.create(art_login=False)
    friend_ids = [x['id'] async for x in bot.get_friends_list()]
    for u in UserConfig.select().where(UserConfig.user_id.in_(friend_ids)):
        assert not u.following
    following_ids = [x['id'] async for x in bot.get_following_list()]
    UserConfig.update(following_main=True).where(
        UserConfig.user_id.in_(following_ids)).execute()
    UserConfig.update(following_main=False).where(
        UserConfig.user_id.not_in(following_ids)).execute()


@app.command(help="Loop through users in database and fetch weibos")
@logsaver_decorator
@run_async
async def user_loop(download_dir: Path = default_path,
                    max_user: int = 1,
                    new_user: bool = Option(False, "--new-user", "-n"),
                    following: bool = Option(False, "--following", "-f")):
    await UserConfig.update_table()
    logsaver = LogSaver('user_loop', download_dir)
    query = (UserConfig.select()
             .where(UserConfig.weibo_fetch)
             .where(~UserConfig.blocked)
             .order_by(UserConfig.weibo_fetch_at, UserConfig.id))

    if new_user:
        users = query.where(UserConfig.weibo_fetch_at.is_null())
        console.log(f'{len(users)} users has been found')
    else:
        query = query.where(UserConfig.weibo_fetch_at.is_null(False))
        if following:
            users = query.where(UserConfig.following | UserConfig.is_friend)
        else:
            users = query.where(~UserConfig.following & ~UserConfig.is_friend)
        if x := users.where(UserConfig.weibo_next_fetch < pendulum.now()):
            max_user = len(x)
            users = x
    users = users[:max_user]
    console.log(f'{len(users)} user(s) will be fetched...')
    for i, user in enumerate(users, start=1):
        try:
            config = await UserConfig.from_id(user_id=user.user_id)
        except UserNotFoundError:
            config = UserConfig.get(user_id=user.user_id)
            config.blocked = True
            config.save()
            console.log(config)
            console.log(
                f'用户 {config.username} 不存在 ({config.homepage})', style='error')
        else:
            await config.fetch_weibo(download_dir)
        console.log(f'user {i}/{len(users)} completed!')
        if new_user:
            logsaver.save_log(save_manually=True, backup=False)
