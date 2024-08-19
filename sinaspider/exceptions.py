class WeiboNotFoundError(Exception):
    def __init__(self, err_msg, url):
        super().__init__(f"{err_msg} for {url}")
        self.err_msg = err_msg
        self.url = url


class UserNotFoundError(Exception):
    pass


class HistLocationError(Exception):
    pass
