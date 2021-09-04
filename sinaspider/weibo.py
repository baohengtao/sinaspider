from collections import OrderedDict
from pathlib import Path
from typing import Union
import pendulum
from sinaspider.helper import logger, get_url, convert_wb_bid_to_id, write_xmp


class Weibo(OrderedDict):
    from sinaspider.database import weibo_table as table

    def __init__(self, *args, **kwargs):
        """
        可通过微博id获取某条微博, 同时支持数字id和bid.
        读取结果将保存在数据库中.
        若微博不存在, 返回 None
        """
        
        first_arg = args[0] if args else None
        if isinstance(first_arg, str):
            if first_arg.isdigit():
                first_arg = int(first_arg)
            else:
                first_arg = convert_wb_bid_to_id(args[0])

        if kwargs or args[1:]:
            super().__init__(*args, **kwargs)
        elif isinstance(first_arg, int):
            wb_info = self._from_weibo_id(first_arg) or {}
            super().__init__(wb_info)
        elif first_arg is None:
            super().__init__()
        else:
            super().__init__(dict(first_arg))
        for k, v in dict(self).items():
            if v is None:
                self.pop(k)

    @classmethod
    def _from_weibo_id(cls, wb_id):
        """从数据库获取微博信息, 若不在其中, 则尝试从网络获取, 并将获取结果存入数据库"""
        assert isinstance(wb_id, int), wb_id
        docu = cls.table.find_one(id=wb_id) or {}
        from sinaspider.parser import get_weibo_by_id
        return cls(docu) or get_weibo_by_id(wb_id)

    def update_table(self):
        """更新数据信息"""
        if self['reposts_count'] == '100万+':
            self['reposts_count'] = 1000000
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
            return self._from_weibo_id(int(original_id)).save_media(download_dir)

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
                continue
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
        wb_map = [
            ('bid', 'ImageUniqueID'),
            ('user_id', 'ImageSupplierID'),
            ('screen_name', 'ImageSupplierName'),
            ('text', 'BlogTitle'),
            ('url', 'BlogURL'),
            ('location', 'Location'),
            ('created_at', 'DateCreated'),
        ]
        for info, xmp in wb_map:
            if v := self.get(info):
                xmp_info[xmp] = v
        xmp_info['DateCreated'] += pendulum.Duration(microseconds=int(sn))
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
        artist = Artist(self['user_id']).to_xmp(with_prefix=True)
        weibo = self.to_xmp(sn=sn, with_prefix=True)
        return weibo | artist 
