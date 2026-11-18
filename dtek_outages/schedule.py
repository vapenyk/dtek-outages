"""Schedule parsing: turns the site's raw JSON into plain intervals.

Pure logic, no network and no terminal, so it is easy to test and reuse.

``fact`` (published schedule) looks like::

    {
      "today": 1794952800,
      "update": "18.11.2026 17:02",
      "data": {
        "1794952800": {
          "GPV3.1": {"1": "yes", "9": "no", "10": "no", "11": "no", ...},
          ...
        }
      }
    }

Hour keys are 1-based: key ``"1"`` is 00:00-01:00, key ``"24"`` is
23:00-24:00.  A missing hour means "yes" (power is on), exactly like the
provider's own page renders it.

``preset`` holds ``time_zone``, which maps an hour key to its labels::

    {"8": ["07-08", "07:00", "08:00"], ...}
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

KYIV_TIMEZONE = "Europe/Kyiv"
FIRST_HOUR = 1
LAST_HOUR = 24

STATUS_TEXT: dict[str, str] = {
    "yes": "є світло",
    "no": "немає",
    "first": "немає (перші 30 хв)",
    "second": "немає (другі 30 хв)",
    "maybe": "можливо",
    "mfirst": "можливо (перші 30 хв)",
    "msecond": "можливо (другі 30 хв)",
}

#: How a status should be coloured: "ok", "off" or "maybe".
STATUS_TONE: dict[str, str] = {
    "yes": "ok",
    "no": "off",
    "first": "off",
    "second": "off",
    "maybe": "maybe",
    "mfirst": "maybe",
    "msecond": "maybe",
}

DEFAULT_STATUS = "yes"


@dataclass(frozen=True)
class Interval:
    """A continuous run of hours with the same status (inclusive bounds)."""

    first_hour: int
    last_hour: int
    status: str

    def __post_init__(self) -> None:
        if not FIRST_HOUR <= self.first_hour <= self.last_hour <= LAST_HOUR:
            raise ValueError(f"invalid interval {self.first_hour}..{self.last_hour}")

    @property
    def text(self) -> str:
        return STATUS_TEXT.get(self.status, self.status)

    @property
    def tone(self) -> str:
        return STATUS_TONE.get(self.status, "")

    @property
    def is_outage(self) -> bool:
        return self.status != DEFAULT_STATUS


def kyiv_tz() -> dt.tzinfo | None:
    """Return the Kyiv timezone, or ``None`` when tzdata is unavailable."""

    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(KYIV_TIMEZONE)
    except Exception:  # missing tzdata / very old Python
        return None


def kyiv_now(now: dt.datetime | None = None) -> dt.datetime:
    """Current time in Kyiv; schedule hours are always Kyiv local hours."""

    moment = now or dt.datetime.now(dt.timezone.utc)
    tz = kyiv_tz()
    if tz is not None:
        return moment.astimezone(tz)
    return moment.astimezone()


def kyiv_date(timestamp: int | str) -> dt.date:
    """Calendar date of a Unix timestamp in Kyiv (the site sends Kyiv midnight)."""

    tz = kyiv_tz()
    moment = dt.datetime.fromtimestamp(int(timestamp), tz=dt.timezone.utc)
    if tz is not None:
        moment = moment.astimezone(tz)
    else:
        moment = moment.astimezone()
    return moment.date()


def format_date(value: dt.date) -> str:
    return value.strftime("%d.%m.%Y")


def day_map(fact: Mapping[str, Any]) -> dict[dt.date, str]:
    """``{date: raw_key}`` for every day present in ``fact['data']``."""

    days: dict[dt.date, str] = {}
    for key in (fact.get("data") or {}):
        try:
            days[kyiv_date(key)] = str(key)
        except (TypeError, ValueError, OSError):
            continue
    return days


def today_key(fact: Mapping[str, Any]) -> str | None:
    """Raw key of the day the provider calls "today"."""

    stamp = fact.get("today")
    if stamp not in (None, "", 0, "0"):
        try:
            return str(int(stamp))
        except (TypeError, ValueError):
            pass
    days = day_map(fact)
    if not days:
        return None
    first = min(days)
    return days[first]


def day_data(fact: Mapping[str, Any], key: str | None) -> Mapping[str, Any] | None:
    """Hours of one day: ``{queue: {hour: status}}``."""

    if key is None:
        return None
    day = (fact.get("data") or {}).get(key)
    return day if isinstance(day, Mapping) else None


def status_at(day: Mapping[str, Any], queue: str, hour: int) -> str:
    hours = day.get(queue) or {}
    return str(hours.get(str(hour), DEFAULT_STATUS))


def intervals(day: Mapping[str, Any], queue: str) -> list[Interval]:
    """Merge consecutive hours with the same status into intervals."""

    result: list[Interval] = []
    current: Interval | None = None
    for hour in range(FIRST_HOUR, LAST_HOUR + 1):
        status = status_at(day, queue, hour)
        if current is not None and current.status == status and current.last_hour + 1 == hour:
            current = Interval(current.first_hour, hour, status)
            continue
        if current is not None:
            result.append(current)
        current = Interval(hour, hour, status)
    if current is not None:
        result.append(current)
    return result


def queue_for(
    day: Mapping[str, Any] | None, candidates: Iterable[str]
) -> str | None:
    """First queue from ``candidates`` that has data for this day."""

    if day is None:
        return None
    for queue in candidates:
        if queue in day:
            return queue
    return None


def time_labels(
    preset: Mapping[str, Any], interval: Interval
) -> tuple[str, str]:
    """Start/end clock labels of an interval, e.g. ``("08:00", "11:00")``."""

    zones = preset.get("time_zone") or {}
    start = _zone_label(zones, interval.first_hour, 1, interval.first_hour - 1)
    end = _zone_label(zones, interval.last_hour, 2, interval.last_hour)
    return start, end


def _zone_label(
    zones: Mapping[str, Any], key: int, index: int, fallback_hour: int
) -> str:
    entry = zones.get(str(key))
    if isinstance(entry, (list, tuple)) and len(entry) > index:
        return str(entry[index])
    return f"{fallback_hour:02d}:00"


def upcoming(
    day: Mapping[str, Any], queue: str, now: dt.datetime
) -> Interval | None:
    """First outage interval that has not finished yet (today only)."""

    current_hour = now.hour + 1
    for interval in intervals(day, queue):
        if interval.is_outage and interval.last_hour >= current_hour:
            return interval
    return None


def first_outage(
    day: Mapping[str, Any], queue: str
) -> Interval | None:
    """First non-``yes`` interval of a day (used for tomorrow)."""

    for interval in intervals(day, queue):
        if interval.is_outage:
            return interval
    return None
