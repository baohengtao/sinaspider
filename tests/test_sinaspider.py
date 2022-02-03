import sys
sys.path.append('..')

from sinaspider.model import *
from sinaspider import console
from python_on_whales import DockerClient
import pytest



@pytest.fixture(scope='session')
def start_docker():
    docker = DockerClient(compose_files=['tests/docker-test.yaml'])
    docker.compose.build()
    docker.compose.up(detach=True)
    database=PostgresqlExtDatabase('sinaspider-test', host='localhost',
                  user='sinaspider-test', password='sinaspider-test', 
                  port='54322')
    bind_database(database)
    database.create_tables([User, UserConfig, Artist, Weibo])
    yield
    docker.compose.down()


def test_start_docker(start_docker):
    pass

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
