
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
      account_id = 'your accout id'
      database_name = 'your_database_name'
      write_xmp=True
   )
   # 读取配置信息
   config()
   ```
4. 设置cookie
   ```python
   import keyring
   cookie = '...your cookie get from www.m.weibo.cn ...'
   keyring.set_password('sinaspider', 'cookie', cookie)
   ```

## 使用

### Owner

```python
>>> from sinaspider import Owner
>>> owner = Owner()
>>> #获取自己的资料
>>> print(owner.info)
id: 6619193364
screen_name: cooper_math
gender: female
...


# 获取自己的关注信息
>>> myfollow = owner.following()
>>> next(myfollow)
{'id': 3486415705,
 'screen_name': '工程师日常',
 'statuses_count': 12799,
 'verified': True,
 ...
}

# 获取自己的微博
>>> myweibo = owner.weibos()
>>> next(myweibo)
{'user_id': 6619193364,
 'screen_name': 'cooper_math',
 'id': 4675511417047078,
 'bid': 'KvGoBtzgy',
 'url': 'https://weibo.com/6619193364/KvGoBtzgy',
 'url_m': 'https://m.weibo.cn/detail/4675511417047078',
 'created_at': DateTime(2021, 8, 29, 12, 44, 11, tzinfo=Timezone('+08:00')),
 'source': 'iPhone',
 'is_pinned': False,
 'photos': {'1': ['https://wx2.sinaimg.cn/large/007dXszily1gtxk6impftj30wi1ycdl9.jpg',
   None]},
 'text': '千万别给我跌到两位数……'}

# 获取收藏页面
>>> mycollection=owner.collections()
>>> next(mycollection)

```
   
### User

```python
>>> from sinaspider import User
>>> uid = 3945696543
>>> user = User.form_user_id(uid)
>>> user
User([('id', 3945696543),
      ('screen_name', '朝阳区第一懒癌选手怼怼酱'),
      ('birthday', '1997-02-12'),
      ('age', 24),
      ('gender', 'female'),
      ('location', '北京 朝阳区'),
      ('homepage', 'https://weibo.com/u/3945696543'),
      ...
      ])

>>> weibos = user.weibos()
{'user_id': 5668580668,
 'screen_name': 'PoemsForYou',
 'id': 4653741938576323,
 'bid': 'Kmy4xzZ5N',
 'url': 'https://weibo.com/5668580668/Kmy4xzZ5N',
 'url_m': 'https://m.weibo.cn/detail/4653741938576323',
 'created_at': DateTime(2021, 6, 30, 11, 0, 3, tzinfo=Timezone('+08:00')),
 'source': '微博 weibo.com',
 'is_pinned': False,
 'text': '请成为永远疯狂永远浪漫永远清澈的存在。太一 | 大幸运术',
 'retweet_by': '朝阳区第一懒癌选手怼怼酱',
 'retweet_by_id': 3945696543,
 'retweet_id': 4653920125456290,
 'retweet_bid': 'KmCHWmTqG',
 'retweet_url': 'https://weibo.com/3945696543/KmCHWmTqG',
 'retweet_text': '好'}

```
