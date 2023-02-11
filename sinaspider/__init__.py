"""
Scraping Weibos
"""
__version__ = '0.4.1'

from rich.console import Console
from rich.theme import Theme

custom_theme = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "error": "bold red"
})
console = Console(theme=custom_theme, record=True)
