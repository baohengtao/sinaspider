
from typer import Typer

from . import config, fetch, weibo

app = Typer()
for app_ in [fetch.app, config.app, weibo.app]:
    app.registered_commands += app_.registered_commands
