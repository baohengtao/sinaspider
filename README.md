
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
birthday: 1994-05-08
location: 北京 海淀区
homepage: https://weibo.com/u/6619193364
description: THU计算数学PHD在读
statuses_count: 312
followers_count: 217
follow_count: 166

# 获取自己的关注信息
>>> myfollow = Owner.following()
>>> next(myfollow)
{'id': 3486415705,
 'screen_name': '工程师日常',
 'statuses_count': 12799,
 'verified': True,
 'verified_type_ext': 1,
 'verified_reason': '搞笑幽默博主',
 'description': '讲述工程师自己的故事！欢迎私信来投稿！',
 'gender': 'male',
 'mbtype': 12,
 'urank': 37,
 'mbrank': 6,
 'following': True,
 'followers_count': 163878,
 'follow_count': 353,
 'avatar_hd': 'https://ww1.sinaimg.cn/orj480/cfce7b59jw1e8qgp5bmzyj2050050aa8.jpg',
 'homepage': 'https://weibo.com/u/3486415705'}

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
{'user_id': 1630705115,
 'screen_name': '云予鱼书',
 'id': 4675343975711702,
 'bid': 'KvC2xnXSe',
 'url': 'https://weibo.com/1630705115/KvC2xnXSe',
 'url_m': 'https://m.weibo.cn/detail/4675343975711702',
 'created_at': DateTime(2021, 8, 29, 1, 38, 50, tzinfo=Timezone('+08:00')),
 'source': 'iPhone客户端',
 'is_pinned': False,
 'photos': {'1': ['https://wx1.sinaimg.cn/large/001MmgTpgy1gtx0y7v2vzj60n014wgrr02.jpg',
   None],
  '2': ['https://wx2.sinaimg.cn/large/001MmgTpgy1gtx0y89rrpj60n014wagc02.jpg',
   None],
  '3': ['https://wx2.sinaimg.cn/large/001MmgTpgy1gtx0y7ync6j60n014wai402.jpg',
   None]},
 'text': '发点子照片要好好修炼一个好脾气'}
>>> 

```
   
### User
