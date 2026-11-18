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
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

KYIV_TIMEZONE = "Europe/Kyiv"  # convenience default, never assumed anywhere
DEFAULT_TIMEZONE_ENV = "DTEK_TIMEZONE"
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


class ZoneError(ValueError):
    """The timezone is neither a known IANA name nor a valid UTC offset."""


class Clock:
    """The provider's clock: day dates and the current local time.

    Nothing assumes Kyiv. A clock either wraps an explicit timezone (an IANA
    name or a fixed offset) or works in *detected* mode, where the offset is
    inferred from the provider's own day keys: every key is local midnight, so
    its UTC time of day reveals the offset the provider published in.  That
    keeps dates and "now" correct for a user in any timezone, and follows
    daylight-saving shifts as long as the provider sends a key per day.
    """

    def __init__(
        self,
        name: str,
        tz: dt.tzinfo | None = None,
        offsets: Mapping[int, dt.timedelta] | None = None,
    ) -> None:
        self.name = name
        self.tz = tz
        self.offsets: dict[int, dt.timedelta] = dict(offsets or {})

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Clock({self.name!r})"

    def __str__(self) -> str:
        return self.name

    def offset_for(self, timestamp: int | float) -> dt.timedelta:
        """UTC offset the provider used for the day containing ``timestamp``."""

        stamp = int(timestamp)
        if self.tz is not None:
            offset = dt.datetime.fromtimestamp(stamp, self.tz).utcoffset()
            return offset or dt.timedelta(0)
        if not self.offsets:
            return dt.timedelta(0)
        if stamp in self.offsets:
            return self.offsets[stamp]
        earlier = [key for key in sorted(self.offsets) if key <= stamp]
        if earlier:
            return self.offsets[earlier[-1]]
        return self.offsets[min(self.offsets)]

    def date(self, timestamp: int | str) -> dt.date:
        """Calendar date of a schedule key, in the provider's timezone."""

        stamp = int(timestamp)
        zone = dt.timezone(self.offset_for(stamp))
        return dt.datetime.fromtimestamp(stamp, zone).date()

    def now(self, moment: dt.datetime | None = None) -> dt.datetime:
        """``moment`` (default: now) expressed in the provider's local time."""

        moment = moment or dt.datetime.now(dt.timezone.utc)
        if self.tz is not None:
            return moment.astimezone(self.tz)
        return moment.astimezone(dt.timezone(self.offset_for(moment.timestamp())))


def offset_label(offset: dt.timedelta) -> str:
    """``timedelta(hours=2)`` -> ``"UTC+02:00"``."""

    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total) // 60, 60)
    if not hours and not minutes:
        return "UTC"
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


_OFFSET_RE = re.compile(r"^(?:UTC|GMT)?([+-])(\d{1,2})(?::?(\d{2}))?$", re.IGNORECASE)
_MIN_OFFSET = dt.timedelta(hours=-12)
_MAX_OFFSET = dt.timedelta(hours=14)


def parse_zone(name: str) -> dt.tzinfo:
    """Turn ``"Europe/Kyiv"`` or ``"+03:00"`` into a ``tzinfo``."""

    cleaned = name.strip()
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(cleaned)
    except Exception:
        pass

    match = _OFFSET_RE.match(cleaned)
    if match:
        sign = -1 if match.group(1) == "-" else 1
        hours = int(match.group(2))
        minutes = int(match.group(3) or 0)
        offset = sign * dt.timedelta(hours=hours, minutes=minutes)
        if minutes < 60 and _MIN_OFFSET <= offset <= _MAX_OFFSET:
            return dt.timezone(offset)

    raise ZoneError(
        f"Невідома часова зона «{name}»: вкажіть IANA-назву (Europe/Kyiv) "
        "або зсув від UTC (+02:00)"
    )


def detect_offsets(
    fact: Mapping[str, Any], moment: dt.datetime | None = None
) -> dict[int, dt.timedelta]:
    """Infer the provider's UTC offsets from its midnight day keys."""

    local = (moment or dt.datetime.now(dt.timezone.utc)).astimezone().utcoffset()
    local = local or dt.timedelta(0)

    offsets: dict[int, dt.timedelta] = {}
    for raw in fact.get("data") or {}:
        try:
            stamp = int(raw)
        except (TypeError, ValueError):
            continue
        utc = dt.datetime.fromtimestamp(stamp, dt.timezone.utc)
        seconds = utc.hour * 3600 + utc.minute * 60 + utc.second
        base = dt.timedelta(seconds=(86400 - seconds) % 86400)
        # A single key cannot tell +13 from -11; prefer offsets that exist,
        # then the one closest to this machine's own offset.
        candidates = [base, base - dt.timedelta(days=1)]
        valid = [item for item in candidates if _MIN_OFFSET <= item <= _MAX_OFFSET]
        offsets[stamp] = min(
            valid or candidates,
            key=lambda item: abs((item - local).total_seconds()),
        )
    return offsets


def system_clock() -> Clock:
    """Last-resort clock: the ``TZ`` variable, else this machine's zone."""

    name = os.environ.get("TZ")
    if name:
        try:
            return Clock(name, tz=parse_zone(name))
        except ZoneError:
            pass
    local = dt.datetime.now().astimezone().tzinfo or dt.timezone.utc
    return Clock(str(local), tz=local)


def resolve_clock(
    fact: Mapping[str, Any] | None = None,
    requested: str | None = None,
    moment: dt.datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> Clock:
    """Build a clock from an explicit zone, ``DTEK_TIMEZONE``, data, or system.

    ``requested`` wins, then ``DTEK_TIMEZONE``.  ``"auto"`` (the default) means
    "detect from the published data", and only when there is no data at all
    does the machine's own timezone step in.
    """

    environment = os.environ if env is None else env
    wanted = (requested or environment.get(DEFAULT_TIMEZONE_ENV) or "").strip()
    if wanted and wanted.lower() not in ("auto", "detect"):
        return Clock(wanted, tz=parse_zone(wanted))

    offsets = detect_offsets(fact or {}, moment)
    if offsets:
        first = offsets[min(offsets)]
        return Clock(f"{offset_label(first)} (auto)", offsets=offsets)
    return system_clock()


def _kyiv_clock() -> Clock:
    try:
        return Clock(KYIV_TIMEZONE, tz=parse_zone(KYIV_TIMEZONE))
    except ZoneError:  # no tzdata on this machine
        return system_clock()


def kyiv_tz() -> dt.tzinfo | None:
    """Kyiv timezone, or ``None`` without tzdata (compatibility helper)."""

    return _kyiv_clock().tz


def kyiv_now(now: dt.datetime | None = None) -> dt.datetime:
    """Current Kyiv time (compatibility helper; prefer :class:`Clock`)."""

    return _kyiv_clock().now(now)


def kyiv_date(timestamp: int | str) -> dt.date:
    """Kyiv calendar date of a timestamp (compatibility helper)."""

    return _kyiv_clock().date(timestamp)


def format_date(value: dt.date) -> str:
    return value.strftime("%d.%m.%Y")


def day_map(
    fact: Mapping[str, Any], clock: Clock | None = None
) -> dict[dt.date, str]:
    """``{date: raw_key}`` for every day present in ``fact['data']``."""

    clock = clock or resolve_clock(fact)
    days: dict[dt.date, str] = {}
    for key in (fact.get("data") or {}):
        try:
            days[clock.date(key)] = str(key)
        except (TypeError, ValueError, OSError):
            continue
    return days


def today_key(fact: Mapping[str, Any], clock: Clock | None = None) -> str | None:
    """Raw key of the day the provider calls "today"."""

    stamp = fact.get("today")
    if stamp not in (None, "", 0, "0"):
        try:
            return str(int(stamp))
        except (TypeError, ValueError):
            pass
    days = day_map(fact, clock)
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
