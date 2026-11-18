#!/usr/bin/env python3
"""Minimal example of using the HTTP client on its own.

    python3 examples/api_usage.py "м. Одеса" "вул. Дерибасівська" 1

Everything below runs on the standard library only, so this file can be
copied together with ``dtek_outages/api.py`` into another project.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import dtek_outages  # noqa: F401  (installed package)
except ImportError:  # running straight from a checkout
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dtek_outages import schedule as sch
from dtek_outages.api import DtekClient, DtekError


def main(city: str, street: str, house_number: str) -> int:
    client = DtekClient()
    try:
        page = client.open()                      # session + CSRF + schedules
        houses = client.houses(city, street)      # {house: queues}
        house = next((h for h in houses if h.number == house_number), None)
        if house is None:
            print(f"No house {house_number!r}; available: "
                  + ", ".join(h.number for h in houses[:10]), file=sys.stderr)
            return 1

        clock = sch.resolve_clock(page.fact)
        print(f"{city}, {street}, {house.number}: queue {house.queues_text}")
        print(f"Provider timezone: {clock.name}")

        key = sch.today_key(page.fact)
        day = sch.day_data(page.fact, key)
        queue = sch.queue_for(day, house.queues)
        if day is None or queue is None:
            print("No published schedule for this queue yet.")
            return 0

        print(f"Updated: {page.fact.get('update', 'n/a')}")
        for interval in sch.intervals(day, queue):
            start, end = sch.time_labels(page.preset, interval)
            print(f"  {start}-{end}  {interval.text}")
        return 0
    except DtekError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
