"""Unofficial DTEK outage schedule client for Odesa region.

Public surface::

    from dtek_outages import DtekClient, House, Clock
    from dtek_outages import schedule, report

Only ``api.py`` talks to the network; everything else is pure Python, which
makes the request code easy to copy into another project.
"""

from .api import DtekClient, DtekError, House, Page, inline_json
from .schedule import Clock, ZoneError, resolve_clock

__version__ = "1.1.0"

__all__ = [
    "Clock",
    "ZoneError",
    "resolve_clock",
    "DtekClient",
    "DtekError",
    "House",
    "Page",
    "inline_json",
    "__version__",
]
