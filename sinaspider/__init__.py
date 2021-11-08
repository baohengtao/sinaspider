import cooper_util

logger = cooper_util.get_logger()

from sinaspider.model import engine, User, Weibo, Artist, Friend, UserConfig
from sinaspider.method import UserMethod, WeiboMethod, UserConfigMethod, ArtistMethod
from sinaspider.util.parser import get_user_by_id, get_weibo_by_id
