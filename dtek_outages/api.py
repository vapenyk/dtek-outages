"""HTTP layer for the DTEK Odesa (DTEK-OEM) shutdowns site.

This module uses only the Python standard library, so it can be copied into
any project as a single file.  Nothing here prints or formats anything: every
function returns plain Python objects.

The site works in three steps:

1. ``GET /ua/shutdowns`` returns an HTML page with a ``csrf-token`` meta tag,
   a session cookie, and two inline JSON blobs (``DisconSchedule.fact`` and
   ``DisconSchedule.preset``) that hold the actually published schedule.
2. ``POST /ua/ajax`` with ``method=getStreets`` returns every settlement and
   its streets.
3. ``POST /ua/ajax`` with ``method=getHomeNum`` returns the houses of one
   street together with the outage queue ("GPV3.1") assigned to each house.

Example::

    from dtek_outages.api import DtekClient

    client = DtekClient()
    streets = client.streets()
    houses = client.houses("Авангардівська ТГ", "Без вулиці")
    page = client.open()
    print(houses[0].number, houses[0].queues, page.fact["today"])
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any

BASE_URL = "https://www.dtek-oem.com.ua"
SHUTDOWNS_PATH = "/ua/shutdowns"
AJAX_PATH = "/ua/ajax"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
)

_CSRF_RE = re.compile(r'name="csrf-token"\s+content="([^"]*)"')


class DtekError(RuntimeError):
    """The site could not be reached, or answered something unexpected."""


@dataclass(frozen=True)
class House:
    """One house on a street and the outage queue(s) it belongs to."""

    number: str
    queues: tuple[str, ...]
    subtype: str = ""
    start: str = ""
    end: str = ""

    @property
    def queues_text(self) -> str:
        return ", ".join(self.queues)


@dataclass(frozen=True)
class Page:
    """The parsed ``/ua/shutdowns`` page: session token and inline schedules."""

    html: str
    csrf: str
    fact: Mapping[str, Any]
    preset: Mapping[str, Any]


def inline_json(html: str, variable: str) -> Any:
    """Return the JSON assigned to ``DisconSchedule.<variable>`` in ``html``.

    ``json.JSONDecoder.raw_decode`` is used instead of a regular expression so
    that nested braces, escaped quotes and unicode escapes are handled by the
    real parser.
    """

    marker = f"DisconSchedule.{variable}"
    start = html.find(marker)
    if start < 0:
        raise DtekError(f"DisconSchedule.{variable} is missing from the page")
    start = html.find("=", start + len(marker))
    if start < 0:
        raise DtekError(f"DisconSchedule.{variable} has no value")
    start += 1
    while start < len(html) and html[start].isspace():
        start += 1
    try:
        value, _ = json.JSONDecoder().raw_decode(html, start)
    except json.JSONDecodeError as exc:
        raise DtekError(f"DisconSchedule.{variable} is not valid JSON: {exc}") from exc
    return value


class DtekClient:
    """A small session-aware client for the public DTEK-OEM endpoints."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = 25.0,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent
        self._cookies = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookies)
        )
        self._csrf: str | None = None
        self._page: Page | None = None

    # -- low level ---------------------------------------------------------
    def url(self, path: str) -> str:
        return self.base_url + path

    def _fetch(self, request: urllib.request.Request) -> bytes:
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            snippet = exc.read()[:300].decode("utf-8", "replace")
            raise DtekError(f"HTTP {exc.code} for {request.full_url}: {snippet}") from exc
        except urllib.error.URLError as exc:
            raise DtekError(f"Cannot reach {request.full_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise DtekError(f"Timed out after {self.timeout:g}s: {request.full_url}") from exc

    def _headers(self, *, ajax: bool = False) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
            # urllib does not decompress bodies, so ask for them verbatim.
            "Accept-Encoding": "identity",
        }
        if ajax:
            headers["X-CSRF-Token"] = self._csrf or ""
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded; charset=UTF-8"
            )
        return headers

    def _ajax(self, payload: Mapping[str, str]) -> Any:
        self.open()
        body = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(
            self.url(AJAX_PATH),
            data=body,
            headers=self._headers(ajax=True),
            method="POST",
        )
        raw = self._fetch(request)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            snippet = raw[:300].decode("utf-8", "replace")
            raise DtekError(f"AJAX did not return JSON: {snippet}") from exc

    # -- public API --------------------------------------------------------
    def open(self) -> Page:
        """Load the shutdowns page once and keep the session for later calls."""

        if self._page is not None:
            return self._page

        request = urllib.request.Request(
            self.url(SHUTDOWNS_PATH), headers=self._headers()
        )
        html = self._fetch(request).decode("utf-8", "replace")

        match = _CSRF_RE.search(html)
        if not match:
            raise DtekError("CSRF token not found on the shutdowns page")
        self._csrf = match.group(1)

        self._page = Page(
            html=html,
            csrf=self._csrf,
            fact=inline_json(html, "fact"),
            preset=inline_json(html, "preset"),
        )
        return self._page

    def streets(self) -> dict[str, list[str]]:
        """Return ``{settlement: [street, ...]}`` for every served address."""

        data = self._ajax({"method": "getStreets"})
        if not _ok(data):
            raise DtekError(f"getStreets failed: {_message(data)}")
        streets = data.get("streets")
        if not isinstance(streets, dict):
            raise DtekError("getStreets returned no 'streets' object")
        return streets

    def houses(self, city: str, street: str = "") -> list[House]:
        """Return the houses of ``street`` in ``city`` with their queues.

        The endpoint ignores the ``house_num`` filter, so the full street is
        always returned and filtering is left to the caller.
        """

        data = self._ajax(
            {
                "method": "getHomeNum",
                "data[0][name]": "city",
                "data[0][value]": city,
                "data[1][name]": "street",
                "data[1][value]": street,
                "data[2][name]": "house_num",
                "data[2][value]": "",
            }
        )
        if not _ok(data):
            raise DtekError(f"getHomeNum failed: {_message(data)}")

        rows = data.get("data")
        if not isinstance(rows, dict):
            raise DtekError("getHomeNum returned no 'data' object")

        houses: list[House] = []
        for number, info in rows.items():
            if number == "-":  # placeholder row used by the site
                continue
            info = info or {}
            queues = info.get("sub_type_reason") or []
            if isinstance(queues, str):
                queues = [queues]
            houses.append(
                House(
                    number=str(number),
                    queues=tuple(str(queue) for queue in queues),
                    subtype=str(info.get("sub_type") or ""),
                    start=str(info.get("start_date") or ""),
                    end=str(info.get("end_date") or ""),
                )
            )
        return houses

    def house(self, city: str, street: str, number: str) -> House:
        """Look up one house by its exact number (``"77"``, ``"/зд 15"``)."""

        for house in self.houses(city, street):
            if house.number == number:
                return house
        raise DtekError(f"House {number!r} not found in {city}, {street!r}")

    def close(self) -> None:
        """Drop the cached page and cookies."""

        self._page = None
        self._csrf = None
        self._cookies.clear()


def _ok(data: Any) -> bool:
    """The site answers ``{"result": true, ...}`` on success."""

    return isinstance(data, Mapping) and data.get("result") in (True, 1, "true")


def _message(data: Any) -> str:
    if isinstance(data, Mapping):
        for key in ("message", "error", "result"):
            value = data.get(key)
            if value and value is not True:
                return str(value)
    return "unexpected response"


def format_queues(queues: Iterable[str]) -> str:
    """``("GPV3.1",)`` -> ``"GPV3.1"`` (helper for UIs)."""

    return ", ".join(queues)
