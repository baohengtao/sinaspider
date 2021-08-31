
##  准备工作
1. 安装 postgresql 数据库(仅确保适用于mac用户):
    ```zsh
    brew install postgresql
    brew services start postgresql
    ```
2. 创建数据库.
   ```zsh
   createdb your_database_name
   ```
3. 配置信息 
   ```python
   from sinaspider import config
   # 写入配置信息
   config(
      account_id = 'your accout id' # 你的微博账号
      database_name = 'your_database_name' # 微博和用户信息将保存在该数据库
      write_xmp=True # 是否将微博信息写入图片(可选, 需安装Exiftool)
   )
   # 读取配置信息
   config()
   >>> ConfigObj({'database_name': 'sina_test', 'write_xmp': 'True', 'account_id': '6619193364'})
   ```
4. 设置cookie
   ```python
   import keyring
   cookie = '...your cookie get from www.m.weibo.cn ...' # 需要m.weibo.cn网页的cookie
   keyring.set_password('sinaspider', 'cookie', cookie)
   ```

## 微博保存与下载
可通过微博id或bid获取某条微博, 若微博不存在, 则返回 None.
所有获取到的结果都将保存在数据库中.
```python
>>> from sinaspider import *
>>> wb_id, wb_bid = 'IqktuyFki', 4462752368262014
>>> assert Weibo(wb_id) == Weibo(wb_bid)
```
下载图片和视频到指定目录:
```python
>>> Weibo(wb_id).save_media(download_dir='path/to/download')
```

### 微博页面
微博页面可通过 `get_weibo_pages`函数获取, 函数签名如下:
```python

def get_weibo_pages(containerid: str,
                    retweet: bool = True,
                    start_page: int = 1,
                    end_page=None,
                    since=None,
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
        since: 从哪天开始爬取, 默认所有时间
        download_dir: 下载目录, 若为空, 则不下载


    Yields:
        Generator[Weibo]: 生成微博实例
    """

```
获取的结果都将保存在数据库中. 若为转发微博, 则数据库中将同时产生原微博和转发微博的两条记录

   
### User
获取用户信息
```python
>>> from sinaspider import User
>>> uid = 6619193364 # 填写 用户id
>>> user = User(uid)
```
可通过`user.weibos`获取微博页面, 其具体参数参加`get_weibo_pages`
```python
# 获取第3页到第10页的所有微博, 并将文件保存在`path/to/download`
weibos=user.weibos(retweet=True, star_page=3, end_page=10, 
                  download_dir='path/to/download')
# 返回下一条微博
next(weibos)
```




### Owner

```python
from sinaspider import Owner
from pathlib import Path
owner = Owner()
#获取自己的资料
owner.info
# 获取自己的关注信息
myfollow = owner.following()
# 获取自己的微博
myweibo = owner.weibos(download_dir='path/to/dir')
# 获取收藏页面
>>> mycollection=owner.collections(download_dir='path/to/dir)
>>> next(mycollection)

```
