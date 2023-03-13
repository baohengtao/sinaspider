from pathlib import Path

import pendulum
import questionary
from rich.prompt import Prompt
from typer import Typer

from sinaspider import console
from sinaspider.helper import download_files, normalize_wb_id
from sinaspider.model import Location, UserConfig, Weibo

from .helper import default_path, logsaver

app = Typer()


@app.command()
def artist():
    from sinaspider.model import Artist
    while username := Prompt.ask('请输入用户名:smile:'):
        if username.isdigit():
            artist = Artist.get_or_none(user_id=int(username))
        else:
            artist = (Artist.select().where(
                Artist.username == username).get_or_none())
        if not artist:
            console.log(f'用户 {username} 不在列表中')
            continue
        console.log(artist)
        if artist.folder == 'new':
            console.log('folder is new, skip')
            continue
        console.print(
            f"which folder ? current is [bold red]{artist.folder}[/bold red]")
        folder = questionary.select("choose folder:", choices=[
            'recent', 'super', 'no-folder']).unsafe_ask()
        if folder == 'no-folder':
            folder = None
        if artist.folder == folder:
            continue
        ques = f'change folder from {artist.folder} to {folder} ?'
        if questionary.confirm(ques).unsafe_ask():
            artist.folder = folder
            artist.save()
            console.print(
                f'{artist.username}: folder changed to [bold red]{folder}[/bold red]')


@app.command(help="fetch weibo by weibo_id")
def weibo(download_dir: Path = default_path):
    while weibo_id := Prompt.ask('请输入微博ID:smile:'):
        if not (weibo_id := normalize_wb_id(weibo_id)):
            continue
        weibo = Weibo.from_id(weibo_id, update=True)
        console.log(weibo)
        if medias := list(weibo.medias(download_dir)):
            console.log(
                f'Downloading {len(medias)} files to dir {download_dir}')
            download_files(medias)


@app.command()
@logsaver
def update_location():
    weibos = (Weibo.select().order_by(Weibo.location_id.desc())
              .where(Weibo.location_id.is_null(False) | Weibo.location_src.is_null(False))
              .where(Weibo.latitude.is_null()))
    for i, weibo in enumerate(weibos):
        console.log(f'✨ processing {i} / {len(weibos)}')
        weibo.update_location()


@app.command()
@logsaver
def fix_location():
    """todo"""
    weibos = (Weibo.select()
              .where(Weibo.location.is_null(False))
              .where(Weibo.location_id.is_null())
              .order_by(Weibo.location))
    for weibo in weibos:
        assert weibo.update_status != 'updated'
        if query := Location.select().where(
                Location.name == weibo.location):
            assert len(query) == 1
            location = query[0]
        else:
            assert not Weibo.select().where(
                Weibo.location == weibo.location).where(Weibo.location_id.is_null(False))
            continue
        weibo.location_id = location.id
        weibo.latitude = location.latitude
        weibo.longitude = location.longitude
        weibo.save()
        console.log(weibo, '\n')


@app.command()
@logsaver
def update_weibo():
    from playhouse.shortcuts import update_model_from_dict

    from sinaspider.exceptions import WeiboNotFoundError
    from sinaspider.parser import WeiboParser
    for weibo in _get_update():
        try:
            weibo_dict = WeiboParser(weibo.id).parse()
        except WeiboNotFoundError as e:
            weibo.username = weibo.user.username
            weibo.update_status = str(e)
            console.log(
                f"{weibo.username}({weibo.url}): :disappointed_relieved: {e}")
        else:
            update_model_from_dict(weibo, weibo_dict)
            weibo.username = weibo.user.username
            console.log(
                f"{weibo.username}({weibo.url}): :tada:  updated successfully!"
            )

        weibo.save()


def _get_update():
    from sinaspider.page import Page
    recent_weibo = (Weibo.select()
                    .where(Weibo.update_status.is_null())
                    .where(Weibo.created_at > pendulum.now().subtract(months=6))
                    .order_by(Weibo.user_id.asc())
                    .order_by(Weibo.id.asc()))
    for i, weibo in enumerate(recent_weibo, start=1):
        console.log(f'✨ processing {i} / {len(recent_weibo)}')
        yield weibo
    console.log(':star2: Weibo in half year have been updated!')
    if not questionary.confirm('Continue?').unsafe_ask():
        return
    uid2visible: dict[int, bool] = {}
    for i, weibo in enumerate(process := Weibo.select()
                              .where(Weibo.update_status.is_null())
                              .order_by(Weibo.user_id.asc()), start=1):
        console.log(f'✨ processing {i} / {len(process)}')
        assert weibo.update_status is None
        assert weibo.created_at < pendulum.now().subtract(months=6)
        if (uid := weibo.user_id) not in uid2visible:
            uid2visible[uid] = (visible := Page(uid).get_visibility())
            if visible:
                if config := UserConfig.get_or_none(user_id=uid):
                    if not config.visible:
                        console.log(
                            f' {config.username}({uid}) is visible!', style='error')
        if not uid2visible[uid]:
            weibo.update_status = 'invisible'
            weibo.username = weibo.user.username
            console.log(
                f"{weibo.username}({weibo.url}): :disappointed_relieved: invisible")
            weibo.save()
        else:
            yield weibo
