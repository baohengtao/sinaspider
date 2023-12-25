"""
Scraping Weibos
"""
__version__ = '0.4.1'

from rich.console import Console
from rich.highlighter import ReprHighlighter
from rich.theme import Theme

ReprHighlighter.highlights += [
    r"(?P<social>(?<![a-z])(ins|ig|instagram)(?![a-z]))",
    r"(?P<social>(小红书|📕))",
]

custom_theme = Theme({
    "info": "dim cyan",
    "warning": "bold bright_yellow on dark_orange",
    "error": "bold bright_red on dark_red",
    "notice": "bold magenta",
    "repr.social": 'bold bright_red on dark_red',
})
console = Console(theme=custom_theme,
                  highlighter=ReprHighlighter(),
                  record=True,
                  width=120)
