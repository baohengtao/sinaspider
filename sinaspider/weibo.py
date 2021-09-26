from __future__ import annotations
from collections import UserDict
from pathlib import Path
from typing import Union

import pendulum

from sinaspider.helper import logger, get_url, convert_wb_bid_to_id, write_xmp


class Weibo(UserDict):
    from sinaspider.database import weibo_table as table
    

    def __init__(self, arg=None, **kwargs):
        from sinaspider.parser import get_weibo_by_id
        self.data, self.id = {}, None
        if isinstance(arg, str):
            arg = int(arg) if arg.isdigit() else convert_wb_bid_to_id(arg)
        if isinstance(arg, int):
            assert not kwargs
            self.id = arg
            self.data = self.table.find_one(id=self.id) or get_weibo_by_id(self.id)
        else:
            super().__init__(arg, **kwargs)
            self.id = self.get('id')
        if not self:
            raise ValueError(self)
        self.data = {k: v for k, v in self.items() if v or v == 0}


    def update_table(self):
        """更新数据信息"""
        for k, v in self.items():
            if v  == '100万+':
                self[k]=1000000
        self.table.upsert(self, ['id'])

    def __str__(self):
        text = ''
        keys = [
            'screen_name', 'id', 'text', 'location',
            'created_at', 'at_users', 'url'
        ]
        for k in keys:
            if v := self.get(k):
                text += f'{k}: {v}\n'
        return text

    def save_media(self, download_dir: Union[str, Path]) -> list:
        """
        保存文件到指定目录. 若为转发微博, 则保持到`retweet`子文件夹中
        Args:
                download_dir (Union[str|Path]): 文件保存目录
        Returns:
                list: 返回下载列表
        """
        download_dir = Path(download_dir)
        if original_id := self.get('original_id'):
            download_dir /= 'retweet'
            self.__class__(original_id).save_media(download_dir)

        download_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{download_dir}/{self['user_id']}_{self['id']}"
        download_list = []
        # add photos urls to list
        for sn, urls in self.get('photos', dict()).items():
            for url in filter(bool, urls):
                ext = url.split('.')[-1]
                filepath = f'{prefix}_{sn}.{ext}'
                download_list.append({
                    'url': url,
                    'filepath': Path(filepath),
                    'xmp_info': self.to_xmp(sn, with_prefix=True)})
        # add video urls to list
        if url := self.get('video_url'):
            assert ';' not in url
            filepath = f'{prefix}.mp4'
            if duration := self.get('video_duration', 0) > 1800:
                logger.warning(f'video_duration is {duration}... skipping...')
            else:
                download_list.append({
                    'url': url,
                    'filepath': Path(filepath),
                    'xmp_info': self.to_xmp(with_prefix=True)})

        # downloading...
        if download_list:
            logger.info(
                f"{self['id']}: Downloading {len(download_list)} files to {download_dir}...")
        for dl in download_list:
            url, filepath = dl['url'], Path(dl['filepath'])
            if filepath.exists():
                logger.warning(f'{filepath} already exists..skip {url}')
            else:
                downloaded = get_url(url).content
                filepath.write_bytes(downloaded)
            write_xmp(dl['xmp_info'], filepath)

        return download_list

    def to_xmp(self, sn=0, with_prefix=False) -> dict:
        """
        Convert to XMP Info

        Args:
                sn (, optional): 图片序列 SeriesNumber 信息 (即图片的次序)
                with_prefix:  是否添加'XMP:'前缀

        Returns:
                dict: 图片元数据
        """
        xmp_info = {}
        if docu := self.table.find_one(original_id=self.id):
            xmp_info['Publisher'] = docu['screen_name']

        wb_map = [
            ('bid', 'ImageUniqueID'),
            ('user_id', 'ImageSupplierID'),
            ('screen_name', 'ImageCreatorName'),
            ('text', 'BlogTitle'),
            ('url', 'BlogURL'),
            ('location', 'Location'),
            ('created_at', 'DateCreated'),
        ]
        for info, xmp in wb_map:
            if v := self.get(info):
                xmp_info[xmp] = v
        xmp_info['DateCreated'] += pendulum.Duration(microseconds=int(sn or 0))
        xmp_info['DateCreated'] = xmp_info['DateCreated'].strftime(
            '%Y:%m:%d %H:%M:%S.%f')
        if sn:
            xmp_info['SeriesNumber'] = sn
        if not with_prefix:
            return xmp_info
        else:
            return {'XMP:' + k: v for k, v in xmp_info.items()}

    def gen_meta(self, sn=0) -> dict:
        from sinaspider.meta import Artist
        artist = Artist(self['user_id']).gen_meta()
        weibo = self.to_xmp(sn=sn, with_prefix=True)
        return weibo | artist
