import os

from configobj import ConfigObj, get_extra_values
from validate import Validator

from sinaspider import logger

_xdg_cache_home = os.environ.get('XDG_CACHE_HOME') or os.environ.get('HOME')
_CONFIG_FILE = os.path.join(_xdg_cache_home, 'sinaspider.ini')


class _Config:
    _fields = ['database_name', 'write_xmp', 'account_id', 'download_dir']

    def __init__(self, config_file):
        configspec = """
                    database_name = string(default=sina)
                    write_xmp = boolean(default=false)
                    download_dir=string(default='~/Downloads/sinaspider')
                    account_id=integer(default=0)
                    """.splitlines()
        self._config = ConfigObj(config_file, configspec=configspec)
        if not self.validate:
            assert False, self._config

    @property
    def validate(self):
        validate = self._config.validate(Validator())
        if validate is not True:
            logger.error(self._config)
            return False
        if x := get_extra_values(self._config):
            logger.error('Find extra values on config: %s' % x)
            return False
        return True

    def __getitem__(self, key):
        return self._config[key]

    def set_key(self, key, value=None, global_=True):
        if value:
            self._config[key] = str(value)
        if not self.validate:
            self._config.reload()
            print(f'{key}:{value} cannot pass validation. roll back...')
        elif global_:
            self._config.write()

        return self._config.get(key)

    def __repr__(self):
        return self._config.__repr__()


config = _Config(_CONFIG_FILE)
