"""
Scraping Weibos
"""
__version__ = '0.4.1'
from rich.console import Console
from rich.progress import Progress
from rich.theme import Theme
from rich import traceback
traceback.install(show_locals=True)
custom_theme = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "error": "bold red"
})
console = Console(theme=custom_theme)
progress = Progress(console=console)
