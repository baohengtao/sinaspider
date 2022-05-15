"""
Scraping Weibos
"""
__version__ = '0.4.1'

from rich import traceback
from rich.console import Console
from rich.theme import Theme
from rich.progress import Progress, BarColumn, TimeRemainingColumn

traceback.install(show_locals=True)
custom_theme = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "error": "bold red"
})
console = Console(theme=custom_theme)



def get_progress():
    return Progress("[progress.description]{task.description}", BarColumn(),
                    "[progress.percentage]{task.completed} of {task.total:>2.0f}({task.percentage:>02.1f}%)",
                    TimeRemainingColumn(), console=console)
