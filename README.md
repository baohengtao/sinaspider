
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
3. 配置基本信息 
   ```python
   from sinaspider import settings
   myset=dict(
      cookie = '...your cookie...(from m.weibo.com)'
      myid = 'your user id'
      database_name = 'your_database_name'
   )
   settings(**myset)
   ```

## 使用

### Owner

```python
>>> from sinaspider import Owner
>>> #获取自己的资料
>>> print(Owner.info)
id: 6619193364
screen_name: cooper_math
gender: female
...


# 获取自己的关注信息
>>> myfollow = Owner.following()
>>> next(myfollow)
{'id': 3486415705,
 'screen_name': '工程师日常',
 'statuses_count': 12799,
 'verified': True,
 ...
}

# 获取自己的微博
>>> myweibo = Owner.weibos()
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
>>> mycollection=Owner.collections()
>>> next(mycollection)

```
   
### User
