import sys

from sinaspider.model import *

sys.path.append('..')
database = init_database('pytest')
DROP_TABLE = True
DROP_TABLE = False


def test_user():
    user_id = 1120967445
    user = User.from_id(user_id)
    for weibo in user.timeline(since=12):
        console.print(weibo)

    return user


def test_weibo():
    wb_id = 'LajbuaB9E'
    weibo = Weibo.from_id(wb_id)
    meta = weibo.gen_meta()
    console.print(f'meta is {meta}')
    for m in weibo.medias():
        console.print(f'medias is {m}')


def test_user_config():
    user_id = 1802628902
    uc = UserConfig.from_id(user_id)
    uc.weibo_update_at = pendulum.now().subtract(months=1)
    uc.fetch_weibo(Path.home() / 'Downloads/pytest_sina')


def test_artist():
    user_id = 1802628902
    print(Artist.from_id(user_id).xmp_info)

