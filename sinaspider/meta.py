import re

import pendulum
from loguru import logger
from unipath import Path

from sinaspider.helper import convert_wb_bid_to_id, pg
from sinaspider.weibo import Weibo

ARTIST_TABLE = 'artist'
artist_table = pg[ARTIST_TABLE]


class WeiboImage:
    def __init__(self):
        self.print_filename = ''

    def gen_meta_from_filename(self, filename, wb_id='', user_id=None, print_filename=''):
        self.print_filename = print_filename or filename
        sn, ext = 0, Path(filename).ext
        wb_info, user_info = {}, {}
        if match := re.match(r'^(\d+)_([^\W_]+)_?(\d*)(\.[A-Za-z1-9]+)$', filename):
            _, wb_id, sn, ext = match.groups()
        if wb_id:
            wb_info = self._from_weibo_id(wb_id, ext, sn)
            user_id = wb_info['user_id']
        if user_id:
            user_info = WeiboArtist.from_user_id(user_id).to_xmp()
        xmp_info = wb_info | user_info
        return xmp_info

    def _from_weibo_id(self, wb_id, ext, sn=0):
        if isinstance(wb_id, str):
            if wb_id.isdigit():
                wb_id = int(wb_id)
            else:
                wb_id = convert_wb_bid_to_id(wb_id)
        assert isinstance(wb_id, int)
        sn = int(sn)
        wb_info = Weibo.from_weibo_id(wb_id)
        if not wb_info:
            logger.warning(
                f'{self.print_filename}=>{wb_id}: not find info')
            return {}
        wb_info['created_at'] = pendulum.instance(
            wb_info['created_at']).add(microseconds=sn)
        rawfilename = f"{wb_info['user_id']}_{wb_info['bid']}"
        rawfilename += ext if not sn else f'_{sn}{ext}'
        wb_info = wb_info.to_xmp()
        wb_info['SeriesNumber'] = sn if sn else ''
        wb_info['RawFileName'] = rawfilename

        return wb_info


class WeiboArtist(dict):

    @classmethod
    def from_user_id(cls, user_id):
        from sinaspider import User
        docu = artist_table.find_one(user_id=user_id)
        user = User.from_user_id(user_id)
        if not docu:
            docu = dict(
                artist=user['screen_name'],
                user_name=user['screen_name'],
                user_id=user['id'],
                homepage=user['homepage'],
                album='微博'
            )

        update_key = {'description', 'gender', 'location', 'education', 'follow_me', 'following',
                      'followers_count', 'follow_count', 'statuses_count', 'age', 'birthday'}
        update = {k: v for k, v in user.items() if k in update_key}
        docu |= update
        artist_table.upsert(docu, ['user_id', ])
        return cls(docu)

    def to_xmp(self):
        return dict(
            Artist=self['artist'],
            ImageCreatorID=self['homepage'],
            ImageSupplierID=self['user_id'],
            ImageSupplierName='Weibo'
        )
