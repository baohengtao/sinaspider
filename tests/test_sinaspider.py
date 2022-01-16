from sinaspider import UserMethod, engine, WeiboMethod
from sqlmodel import Session
def test_user():
    uid=2715204863
    with Session(engine) as session:
        user=UserMethod.from_id(uid, session=session)
    assert user.id==uid

def test_weibo_id():
    wid=4696094896293270
    from sinaspider.util.parser import get_weibo_by_id
    nt_weibo = get_weibo_by_id(wid)
    with Session(engine) as session:
        weibo=WeiboMethod.from_id(wid, session)
        weibo, original = nt_weibo
        wb=WeiboMethod.add_to_table(weibo, original, session=session)[0]
        assert wb.id == wid