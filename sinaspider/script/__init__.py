
from typer import Typer

from . import database, liked, timeline, user

app = Typer()
for app_ in [user.app, liked.app, database.app, timeline.app]:
    app.registered_commands += app_.registered_commands
