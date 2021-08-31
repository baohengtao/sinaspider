from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Union, Generator

import pendulum

from sinaspider.helper import logger, get_url, get_json, pause, convert_wb_bid_to_id


class Weibo(OrderedDict):
    from sinaspider.database import weibo_table as table
    from sinaspider.helper import config as _config
    if _config().as_bool('write_xmp'):
        from exiftool import ExifTool
        et = ExifTool()
        et.start()
    else:
        et = None

    def __init__(self, *args, **kwargs):
        """
        可通过微博id获取某条微博, 同时支持数字id和bid.
        读取结果将保存在数据库中.
        若微博不存在, 返回 None
        """
        wb_id = args[0]
        if isinstance(wb_id, str):
            if wb_id.isdigit():
                wb_id = int(wb_id)
            else:
                wb_id = convert_wb_bid_to_id(args[0])
        if kwargs or args[1:] or not isinstance(wb_id, int):
            super().__init__(*args, **kwargs)
        else:
            super().__init__(self._from_weibo_id(wb_id))

    @classmethod
    def _from_weibo_id(cls, wb_id):
        """从数据库获取微博信息, 若不在其中, 则尝试从网络获取, 并将获取结果存入数据库"""
        assert isinstance(wb_id, int), wb_id
        docu = cls.table.find_one(id=wb_id) or {}
        from sinaspider.parser import get_weibo_by_id
        return cls(docu) or get_weibo_by_id(wb_id)

    def update_table(self):
        """更新数据信息"""
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
            return self._from_weibo_id(original_id).save_media(download_dir)
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
            if self.et:
                self.et.set_tags(dl['xmp_info'], str(filepath))
                filepath.with_name(filepath.name + '_original').unlink()

        return download_list

    def to_xmp(self, sn=0, with_prefix=False) -> dict:
        """
        生产图片元数据

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
        xmp_info['DateCreated'] = xmp_info['DateCreated'].strftime(
            '%Y:%m:%d %H:%M:%S.%f')
        if sn:
            xmp_info['SeriesNumber'] = sn
        if not with_prefix:
            return xmp_info
        else:
            return {'XMP:' + k: v for k, v in xmp_info.items()}


def get_weibo_pages(containerid: str,
                    retweet: bool = True,
                    start_page: int = 1,
                    end_page=None,
                    since: Union[int, str, datetime] = '1970-01-01',
                    download_dir=None
                    ) -> Generator[Weibo, None, None]:
    """
    爬取某一 containerid 类型的所有微博

    Args:
        containerid(str): 
            - 获取用户页面的微博: f"107603{user_id}"
            - 获取收藏页面的微博: 230259
        retweet (bool): 是否爬取转发微博
        start_page(int): 指定从哪一页开始爬取, 默认第一页.
        end_page: 终止页面, 默认爬取到最后一页
        since: 若为整数, 从哪天开始爬取, 默认所有时间
        download_dir: 下载目录, 若为空, 则不下载


    Yields:
        Generator[Weibo]: 生成微博实例
    """
    if isinstance(since, int):
        assert since > 0
        since = pendulum.now().subtract(since)
    elif isinstance(since, str):
        since = pendulum.parse(since)
    else:
        since = pendulum.instance(since)
    page = max(start_page, 1)
    while True:
        js = get_json(containerid=containerid, page=page)
        if not js['ok']:
            if js['msg'] == '请求过于频繁，歇歇吧':
                logger.critical('be banned')
                return js
            else:
                logger.warning(
                    f"not js['ok'], seems reached end, no wb return for page {page}")
                break

        mblogs = [w['mblog']
                  for w in js['data']['cards'] if w['card_type'] == 9]

        for weibo_info in mblogs:
            if weibo_info.get('retweeted_status') and not retweet:
                logger.info('过滤转发微博...')
                continue
            from sinaspider.parser import parse_weibo
            weibo = parse_weibo(weibo_info)
            if not weibo:
                continue
            if weibo['created_at'] < since:
                if weibo['is_pinned']:
                    logger.warning(f"发现置顶微博, 跳过...")
                    continue
                else:
                    logger.info(
                        f"时间{weibo['created_at']} 在 {since:%y-%m-%d}之前, 获取完毕")
                    end_page = page
                    break

            if download_dir:
                weibo.save_media(download_dir)
            yield weibo

        logger.success(f"++++++++ 页面 {page} 获取完毕 ++++++++++\n")
        page += 1
        if end_page and page > end_page:
            break
        pause(mode='page')
