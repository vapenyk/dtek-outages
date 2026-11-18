"""Presentation layer: a readable text report and a machine-readable dict."""

from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

from . import schedule as sch
from .api import House

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
TONE_COLORS = {"ok": "\x1b[32m", "off": "\x1b[31m", "maybe": "\x1b[33m"}


class Style:
    """Minimal ANSI helper; every call is a no-op when colour is disabled."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"{code}{text}{RESET}"

    def bold(self, text: str) -> str:
        return self._wrap(BOLD, text)

    def dim(self, text: str) -> str:
        return self._wrap(DIM, text)

    def status(self, interval: sch.Interval) -> str:
        color = TONE_COLORS.get(interval.tone)
        if not color:
            return interval.text
        return self._wrap(color, interval.text)


def address_label(city: str, street: str, house: str) -> str:
    parts = [city]
    if street:
        parts.append(street)
    parts.append(house)
    return ", ".join(parts)


def _day_context(
    fact: Mapping[str, Any],
    preset: Mapping[str, Any],
    clock: sch.Clock,
) -> tuple[
    dt.date | None,
    str | None,
    Mapping[str, Any] | None,
    dt.date | None,
    str | None,
    Mapping[str, Any] | None,
]:
    """Resolve today's and tomorrow's raw keys, dates and hour maps."""

    key_today = sch.today_key(fact, clock)
    date_today = clock.date(key_today) if key_today else None

    key_tomorrow: str | None = None
    date_tomorrow: dt.date | None = None
    if date_today is not None:
        date_tomorrow = date_today + dt.timedelta(days=1)
        key_tomorrow = sch.day_map(fact, clock).get(date_tomorrow)

    return (
        date_today,
        key_today,
        sch.day_data(fact, key_today),
        date_tomorrow,
        key_tomorrow,
        sch.day_data(fact, key_tomorrow),
    )


def text_report(
    *,
    city: str,
    street: str,
    house: House,
    queues: Sequence[str],
    fact: Mapping[str, Any],
    preset: Mapping[str, Any],
    now: dt.datetime | None = None,
    clock: sch.Clock | None = None,
    color: bool = True,
) -> list[str]:
    """Build the human-readable report as a list of lines."""

    style = Style(color)
    clock = clock or sch.resolve_clock(fact, moment=now)
    moment = clock.now(now)
    queues = [queue for queue in queues if queue]

    (
        date_today,
        _key_today,
        day_today,
        date_tomorrow,
        key_tomorrow,
        day_tomorrow,
    ) = _day_context(fact, preset, clock)

    queue_today = sch.queue_for(day_today, queues)
    queue_tomorrow = sch.queue_for(day_tomorrow, queues)

    blocks: list[list[str]] = []

    header = [style.bold(address_label(city, street, house.number))]
    if date_today is not None:
        header.append(f"Дата: {sch.format_date(date_today)}")
    if queues:
        header.append(f"Черга: {', '.join(queues)}")
    blocks.append(header)

    # -- current notice ----------------------------------------------------
    current = [f"{style.bold('Зараз:')} {house.subtype}"]
    if house.subtype and house.start:
        current.append(f"  {house.start} — {house.end}")
    elif queues:
        current = [f"{style.bold('Зараз:')} даних про активне відключення немає"]
    else:
        current = [
            f"{style.bold('Зараз:')} інформації про відключення за адресою немає"
        ]
    blocks.append(current)

    # -- today -------------------------------------------------------------
    if day_today is not None and queue_today is not None:
        today = _schedule_block(
            style,
            f"Графік на сьогодні ({queue_today}):",
            sch.intervals(day_today, queue_today),
            preset,
        )
        nearest = sch.upcoming(day_today, queue_today, moment)
        if nearest is not None:
            start, _end = sch.time_labels(preset, nearest)
            today.append(
                f"{style.bold('Найближче:')} з {start} — {style.status(nearest)}"
            )
        else:
            today.append("Найближче: на сьогодні більше відключень не видно")
        blocks.append(today)

    # -- tomorrow ----------------------------------------------------------
    title = "Завтра"
    if date_tomorrow is not None:
        title = f"Завтра ({sch.format_date(date_tomorrow)})"

    if key_tomorrow is None:
        blocks.append(
            [
                f"{style.bold(title + ':')} інформація від НЕК «Укренерго» "
                "про обмеження на наступний день ще не надходила"
            ]
        )
    elif not queues:
        blocks.append([f"{style.bold(title + ':')} немає даних для вашої адреси"])
    elif queue_tomorrow is None:
        blocks.append(
            [f"{style.bold(title + ':')} даних для черги {', '.join(queues)} ще немає"]
        )
    else:
        tomorrow = _schedule_block(
            style,
            f"Графік на завтра ({sch.format_date(date_tomorrow)}, {queue_tomorrow}):",
            sch.intervals(day_tomorrow, queue_tomorrow),
            preset,
        )
        nearest = sch.first_outage(day_tomorrow, queue_tomorrow)
        if nearest is not None:
            start, _end = sch.time_labels(preset, nearest)
            tomorrow.append(
                f"{style.bold('Найближче завтра:')} з {start} — {style.status(nearest)}"
            )
        else:
            tomorrow.append("Завтра відключень за графіком не видно")
        blocks.append(tomorrow)

    updated = fact.get("update")
    if updated:
        blocks.append([style.dim(f"Оновлено: {updated}")])

    lines: list[str] = [""]
    for index, block in enumerate(blocks):
        if index:
            lines.append("")
        lines.extend(block)
    return lines


def _schedule_block(
    style: Style,
    title: str,
    intervals: Sequence[sch.Interval],
    preset: Mapping[str, Any],
) -> list[str]:
    lines = [style.bold(title)]
    for interval in intervals:
        start, end = sch.time_labels(preset, interval)
        lines.append(f"  {start}–{end}   {style.status(interval)}")
    lines.append("")
    return lines


def json_report(
    *,
    city: str,
    street: str,
    house: House,
    queues: Sequence[str],
    fact: Mapping[str, Any],
    preset: Mapping[str, Any],
    now: dt.datetime | None = None,
    clock: sch.Clock | None = None,
) -> dict[str, Any]:
    """Same information as :func:`text_report`, shaped for scripts."""

    clock = clock or sch.resolve_clock(fact, moment=now)
    moment = clock.now(now)
    queues = [queue for queue in queues if queue]

    (
        date_today,
        _key_today,
        day_today,
        date_tomorrow,
        key_tomorrow,
        day_tomorrow,
    ) = _day_context(fact, preset, clock)

    queue_today = sch.queue_for(day_today, queues)
    queue_tomorrow = sch.queue_for(day_tomorrow, queues)

    return {
        "address": {
            "city": city,
            "street": street,
            "house": house.number,
            "label": address_label(city, street, house.number),
        },
        "queues": list(queues),
        "source": {
            "updated": fact.get("update") or None,
            "today_key": sch.today_key(fact, clock),
            "timezone": clock.name,
        },
        "now": {
            "local_time": moment.strftime("%H:%M"),
            "date": sch.format_date(moment.date()),
        },
        "current": {
            "sub_type": house.subtype or None,
            "start": house.start or None,
            "end": house.end or None,
        },
        "today": _day_json(date_today, day_today, queue_today, preset),
        "tomorrow": _day_json(
            date_tomorrow,
            day_tomorrow if key_tomorrow is not None else None,
            queue_tomorrow,
            preset,
        ),
        "announced": key_tomorrow is not None,
    }


def _day_json(
    date: dt.date | None,
    day: Mapping[str, Any] | None,
    queue: str | None,
    preset: Mapping[str, Any],
) -> dict[str, Any] | None:
    if date is None:
        return None
    payload: dict[str, Any] = {"date": sch.format_date(date), "queue": queue}
    if day is None or queue is None:
        payload["intervals"] = []
        return payload

    entries = []
    for interval in sch.intervals(day, queue):
        start, end = sch.time_labels(preset, interval)
        entries.append(
            {
                "from": start,
                "to": end,
                "status": interval.status,
                "status_text": interval.text,
                "outage": interval.is_outage,
            }
        )
    payload["intervals"] = entries
    return payload
