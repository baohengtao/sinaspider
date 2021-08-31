
## 准备工作
1. 安装 postgresql 数据库:
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

## Quick Start
将关注者放入配置列表中:
```python
from sinaspider.user import Owner
from sinaspider.user_config import UserConfig
owner = Owner()
for following in owner.following():
    UserConfig(following)
```

读取配置列表中的用户:

```python
>>> for user_config in UserConfig.yield_config_user():
>>>     pring(user_config)
>>>     break
# 打开所有配置选项
>>> user_config.toggle_all()
Fetch Weibo: True
Fetch Retweet: True
Download Media: True
Fetch following: True
# 获取所有微博
>>> user_config.fetch_weibo()
Fetching Retweet: True
Media Saving: ~/Downloads/sinaspider
Update Config: True
```
每个用户提供如下配置选项:
1. `weibo_fetch`: 是否下载微博
4. `weibo_since`: 只获取该日期后的微博(默认为`1970-01-01`, 即获取所有微博)
2. `retweet_fetch`: 是否下载转发微博
3. `media_download`: 是否下载图片和视频








## 微博保存与下载




   
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
