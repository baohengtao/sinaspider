import pickle
from pathlib import Path

import pendulum

from sinaspider import console

from .base import database
from .config import UserConfig
from .user import Artist, Friend, User
from .weibo import Location, Weibo, WeiboLiked, WeiboMissed

tables = [User, UserConfig, Artist, Weibo,
          WeiboLiked, Location, Friend, WeiboMissed]
database.create_tables(tables)


class PG_BACK:
    def __init__(self, backpath: Path) -> None:
        self.backpath = backpath
        self.backpath.mkdir(exist_ok=True)
        self.backfile = self.backpath / 'pg_backup_latest.pkl'

    def backup(self):
        filename = f"pg_back_{pendulum.now():%Y%m%d_%H%M%S}.pkl"
        backfile = self.backpath / filename
        console.log(f'backuping database to {backfile}...')
        databse_backup = {table._meta.table_name: list(
            table) for table in tables}
        with backfile.open('wb') as f:
            pickle.dump(databse_backup, f)
        if self.backfile.exists():
            self.backfile.unlink()
        self.backfile.hardlink_to(backfile)

    def restore(self):
        if not self.backfile.exists():
            console.log('No backup file found.', style='error')
            return
        with self.backfile.open('rb') as f:
            return pickle.load(f)
