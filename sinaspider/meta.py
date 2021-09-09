class Artist(dict):
    from sinaspider.database import artist_table as table

    def __init__(self, *args, **kwargs):
        if kwargs:
            assert not args
            super().__init__(**kwargs)
        elif args:
            assert len(args) == 1
            if isinstance(args[0], dict):
                super().__init__(args[0])
            else:
                uid = int(args[0])
                super().__init__(self._from_user_id(uid))
        else:
            super().__init__()

    @classmethod
    def _from_user_id(cls, uid):
        from sinaspider import User
        uid = int(uid)
        user = User(uid)
        assert user
        docu = cls.table.find_one(id=uid)
        if not docu:
            docu = dict(
                artist=user['screen_name'],
                user_name=user['screen_name'],
                album='微博'
            )
        docu.update(user)
        artist = cls({k: v for k, v in docu.items() if v})
        artist.update_table()
        return cls(cls.table.find_one(id=uid))

    def update_table(self):
        self.table.upsert(self, ['id'], ensure=False)

    def gen_meta(self):
        if not self:
            return {}
        xmp = dict(
            Artist=self['artist'],
            ImageCreatorID=self['homepage'],
            ImageSupplierID=self['id'],
            ImageSupplierName='Weibo'
        )
        return {'XMP:' + k: v for k, v in xmp.items()}
