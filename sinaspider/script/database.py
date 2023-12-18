from pathlib import Path

import pendulum
import questionary
from photosinfo.model import Photo
from rich.prompt import Prompt
from typer import Typer

from sinaspider import console
from sinaspider.exceptions import WeiboNotFoundError
from sinaspider.helper import download_files, fetcher, normalize_wb_id
from sinaspider.model import Artist, User, UserConfig, Weibo
from sinaspider.parser import WeiboParser

from .helper import default_path, logsaver_decorator

app = Typer()


@app.command(help="fetch weibo by weibo_id")
@logsaver_decorator
def weibo(download_dir: Path = default_path):
    while weibo_id := Prompt.ask('请输入微博ID:smile:'):
        fetcher.toggle_art(True)
        if not (weibo_id := normalize_wb_id(weibo_id)):
            continue
        weibo = Weibo.from_id(weibo_id, update=True)
        console.log(weibo)
        if medias := list(weibo.medias(download_dir)):
            console.log(
                f'Downloading {len(medias)} files to dir {download_dir}')
            download_files(medias)


@app.command()
@logsaver_decorator
def update_missing():
    from sinaspider.model import WeiboMissed

    from .helper import LogSaver
    logsaver = LogSaver('update_missing', default_path)
    WeiboMissed.add_missing()
    while True:
        WeiboMissed.update_missing()
        logsaver.save_log()


@app.command()
@logsaver_decorator
def update_location():
    photos = (Photo.select()
              .where(Photo.image_supplier_name == "Weibo")
              .where(Photo.location.is_null(False))
              .where(Photo.image_unique_id.is_null(False)))
    bids = {p.image_unique_id for p in photos}
    weibos = (Weibo.select()
              .order_by(Weibo.user_id.desc(), Weibo.id.desc())
              .where(Weibo.bid.in_(bids))
              .where(Weibo.location_id.is_null(False))
              .where(Weibo.latitude.is_null()))
    for i, weibo in enumerate(weibos, start=1):
        console.log(f'✨ processing {i} / {len(weibos)}')
        try:
            weibo.update_location()
        except AssertionError:
            console.log(
                f'failed to get location for {weibo.url}', style='error')
        console.log(weibo, '\n')


@app.command()
@logsaver_decorator
def update_weibo(download_dir: Path = default_path):

    for weibo in _get_update():
        fetcher.toggle_art(weibo.user.following)
        try:
            weibo_dict = WeiboParser(weibo.id).parse()
        except WeiboNotFoundError as e:
            weibo.try_update_at = pendulum.now()
            weibo.try_update_msg = str(e).removesuffix(
                f' for https://m.weibo.cn/detail/{weibo.id}')
            weibo.save()
            console.log(
                f"{weibo.username} ({weibo.url}): :disappointed_relieved: {e}")
            continue
        try:
            Weibo.upsert(weibo_dict)
        except ValueError as e:
            console.log(f'value error: {e}', style='error')
            console.log(weibo)
        else:
            weibo = Weibo.from_id(weibo.id)
            download_files(weibo.medias(
                download_dir/'fix_location'/weibo.username, extra=True))
            weibo.photos_extra = None
            weibo.save()
            console.log(weibo)
            console.log()

            console.log(
                f"{weibo.username} ({weibo.url}): :tada:  updated successfully!"
            )


def _get_update():
    from sinaspider.page import Page
    assert not Weibo.select().where(Weibo.photos_extra.is_null(False))
    photos = (Photo.select()
              .where(Photo.image_supplier_name == "Weibo")
              .where(Photo.image_unique_id.is_null(False)))
    bids = {p.image_unique_id for p in photos}
    query = (Weibo.select()
             .where(Weibo.bid.in_(bids))
             .where(Weibo.update_status != 'updated')
             .where(Weibo.try_update_at.is_null())
             .order_by(Weibo.user_id.desc(), Weibo.id.desc())
             )
    recent_weibo = query.where(
        Weibo.created_at > pendulum.now().subtract(months=6))
    other_weibo = query.where(
        Weibo.created_at <= pendulum.now().subtract(months=6))
    for i, weibo in enumerate(recent_weibo, start=1):
        console.log(f'✨ processing {i} / {len(recent_weibo)}')
        yield weibo
    console.log(':star2: Weibo in half year have been updated!')
    uid2visible: dict[int, bool] = {}
    for i, weibo in enumerate(other_weibo, start=1):
        console.log(f'✨ processing {i} / {len(query)}')
        if (uid := weibo.user_id) not in uid2visible:
            uid2visible[uid] = (visible := Page(uid).get_visibility())
            if visible:
                if config := UserConfig.get_or_none(user_id=uid):
                    if not config.visible:
                        raise ValueError(
                            f'{config.username} ({uid}) is visible!')
        if not uid2visible[uid]:
            weibo.try_update_at = pendulum.now()
            weibo.try_update_msg = 'invisible'
            weibo.username = weibo.user.username
            console.log(
                f"{weibo.username} ({weibo.url}): 😥 invisible")
            weibo.save()
        else:
            yield weibo


@app.command()
def database_clean(dry_run: bool = False):

    if not dry_run:
        if not questionary.confirm('Have you backup database to rpi?').ask():
            console.log('Backup first, bye!')
            return
        if not questionary.confirm(
                'Have you put all photos to Photos.app?').ask():
            console.log('put them to Photos.app first, bye!')
            return

    photos = (Photo.select()
              .where(Photo.image_supplier_name == "Weibo")
              .where(Photo.image_unique_id.is_null(False)))
    photo_bids = {p.image_unique_id for p in photos}
    console.log(f'{len(photo_bids)} weibos in photos.app\n'
                f'{len(Weibo)} weibos in sina database')
    if dry_run:
        to_del = (Weibo.select()
                  .where(Weibo.bid.not_in(photo_bids))
                  .order_by(Weibo.user_id))
        console.log(f'{len(to_del)} weibos will be deleted\n')
        for w in to_del:
            console.log(w, '\n')
        uids = {u.user_id for u in UserConfig} | {u.user_id for u in Artist}
        to_del = User.select().where(User.id.not_in(uids))
        console.log(f'{len(to_del)} users will be deleted\n')
        for u in to_del:
            console.log(u, '\n')
    else:
        del_count = (Weibo.delete()
                     .where(Weibo.bid.not_in(photo_bids))
                     .execute())
        console.log(f'{del_count} weibos have been deleted\n'
                    f'{len(Weibo)} weibos left in sina database')
        uids = {u.user_id for u in UserConfig} | {u.user_id for u in Artist}
        del_count = User.delete().where(User.id.not_in(uids)).execute()
        console.log(f'{del_count} users have been deleted')
        console.log('Done!')
