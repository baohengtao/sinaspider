
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
3. 设置 `m.weibo.com`的cookie
   ```python
   import keyring
   cookie = "...your cookie..."
   keyring.set_password('sinaspider', 'cookie', cookie)
   ```
### 配置数据库名称
数据库名称将依次按如下顺序读取
1. 环境变量
   ```shell
   export SINA_SPIDER_DATABASE=your_database_name
   ```
2. keyring
   ```python
   import keyrimg
   keyring.set_password('sinaspider', 'database', 'your_database_name')
   ````
3. 默认值: sina


## 使用
   
