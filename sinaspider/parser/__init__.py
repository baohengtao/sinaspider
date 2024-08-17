from .user import UserParser


async def parse_weibo(mblog: dict, hist_mblogs=None) -> dict:
    from .web import parse_weibo_from_web
    from .weico import parse_weibo_from_weico

    if 'web' in (mblog_from := mblog['mblog_from']):
        return await parse_weibo_from_web(mblog, hist_mblogs)
    else:
        assert 'weico' in mblog_from
        return parse_weibo_from_weico(mblog, hist_mblogs)


__all__ = ['UserParser', 'parse_weibo']
