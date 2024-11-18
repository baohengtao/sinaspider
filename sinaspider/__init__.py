"""
Scraping Weibos
"""
__version__ = '0.4.1'

from rich.console import Console
from rich.highlighter import ReprHighlighter
from rich.theme import Theme

ReprHighlighter.highlights += [
    r"(?P<social>(?<![a-zA-Z])(ins|ig|instagram|IG|INS|Ins|dy|xhs)"
    r"(?![a-zA-Z]))",
    r"(?P<social>(小红书|📕|抖音|🍠))",
]

custom_theme = Theme({
    "info": "dim cyan",
    "warning": "bold bright_yellow on dark_goldenrod",
    "error": "bold bright_red on dark_red",
    "notice": "bold magenta",
    "repr.social": 'bold bright_red on dark_red',
})
console = Console(theme=custom_theme,
                  highlighter=ReprHighlighter(),
                  record=True,
                  width=120)
