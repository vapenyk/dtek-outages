"""Unofficial DTEK outage schedule client for Odesa region.

Public surface::

    from dtek_outages import DtekClient, House
    from dtek_outages import schedule, report

Only ``api.py`` talks to the network; everything else is pure Python, which
makes the request code easy to copy into another project.
"""

from .api import DtekClient, DtekError, House, Page, inline_json

__version__ = "1.0.0"

__all__ = [
    "DtekClient",
    "DtekError",
    "House",
    "Page",
    "inline_json",
    "__version__",
]
