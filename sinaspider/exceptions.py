class WeiboNotFoundError(Exception):
    def __init__(self, err_msg, url):
        super().__init__(f"{err_msg} for {url}")
        self.err_msg = err_msg
        self.url = url


class UserNotFoundError(Exception):
    pass


class HistError(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.weibo_dict = args[0]


class DownloadFilesFailed(Exception):
    def __init__(self, imgs, errs) -> None:
        super().__init__()
        self.imgs = imgs
        self.errs = errs
