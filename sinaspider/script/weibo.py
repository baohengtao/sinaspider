from pathlib import Path

import pendulum
import questionary
from rich.prompt import Prompt
from typer import Typer

from sinaspider import console
from sinaspider.helper import download_files, normalize_wb_id
from sinaspider.model import UserConfig, Weibo

from .helper import default_path, logsaver

app = Typer()


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
def weibo_update():
    from playhouse.shortcuts import update_model_from_dict

    from sinaspider.exceptions import WeiboNotFoundError
    from sinaspider.parser import WeiboParser
    for weibo in get_update():
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


def get_update():
    from sinaspider.page import Page
    recent_weibo = (Weibo.select()
                    .where(Weibo.update_status.is_null())
                    .where(Weibo.created_at > pendulum.now().subtract(months=6))
                    .order_by(Weibo.user_id.asc()))
    for i, weibo in enumerate(recent_weibo, start=1):
        if i % 20 == 0:
            console.log(f'✨ processing {i} / {len(recent_weibo)}')
        yield weibo
    console.log(':star2: Weibo in half year have been updated!')
    if not questionary.confirm('Continue?').unsafe_ask():
        return
    uid2visible: dict[int, bool] = {}
    for i, weibo in enumerate(process := Weibo.select()
                              .where(Weibo.update_status.is_null())
                              .order_by(Weibo.user_id.asc()), start=1):
        if i % 10 == 0:
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
