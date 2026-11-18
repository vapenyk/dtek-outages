# dtek-outages

[![tests](https://github.com/vapenyk/dtek-outages/actions/workflows/tests.yml/badge.svg)](https://github.com/vapenyk/dtek-outages/actions/workflows/tests.yml)

Unofficial command-line client for the **DTEK Odesa (DTEK-OEM) power outage
schedules**. Pick a settlement → street → house once, and get the published
schedule for that address, its outage queue and the current notice.

```text
Авангардівська ТГ, Без вулиці, 77
Дата: 18.11.2026
Черга: GPV3.1

Зараз: даних про активне відключення немає

Графік на сьогодні (GPV3.1):
  00:00–08:00   є світло
  08:00–11:00   немає
  11:00–24:00   є світло

Найближче: на сьогодні більше відключень не видно

Завтра (19.11.2026): інформація від НЕК «Укренерго» про обмеження на наступний день ще не надходила

Оновлено: 18.11.2026 17:02
```

* **Zero dependencies** — Python 3.9+ standard library only.
* **Linux, macOS and \*BSD** (no GNU-only `date`, `grep -P` or `stat` tricks).
* **fzf is optional** — without it you get a plain numbered prompt.
* **Copyable API layer**: all network code lives in a single file,
  [`dtek_outages/api.py`](dtek_outages/api.py), with no other imports.
* **JSON output** for bars, scripts and dashboards.
* **No hardcoded timezone** — the provider's UTC offset is derived from its own
  day keys, and `--timezone` overrides it.
* **42 unit tests**, no network needed.

Українська версія: [README.uk.md](README.uk.md).

## Requirements

| Component | Needed | Notes |
|---|---|---|
| Python | 3.9 or newer | `python3 --version` |
| `fzf` | optional | nicer picker; install with your package manager (`brew install fzf`, `pkg install fzf`, `apt install fzf`) |
| Network | yes | `https://www.dtek-oem.com.ua` |
| `tzdata` | usually present | needed only for named zones (`--timezone Europe/Kyiv`) |

## Install

Run straight from a checkout:

```bash
git clone https://github.com/vapenyk/dtek-outages.git
cd dtek-outages
./dtek-outages
```

Install as a command (any of these):

```bash
pipx install .            # isolated, recommended
python3 -m pip install .  # into the current environment
make install              # same as: python3 -m pip install --user .
```

Then:

```bash
dtek-outages
```

## Usage

```bash
# interactive: settlement -> street -> house
dtek-outages

# non-interactive
dtek-outages --city "Авангардівська ТГ" --street "Без вулиці" --house 77

# a settlement without streets
dtek-outages --city "с. Тест" --street "" --house 5

# machine-readable
dtek-outages --city "м. Одеса" --street "вул. Дерибасівська" --house 1 --json
```

### Options

| Option | Meaning |
|---|---|
| `--city NAME` | settlement; skips the city picker |
| `--street NAME` | street; `''` for settlements without streets |
| `--house NUMBER` | house number (e.g. `77`, `/зд 15`) |
| `--json` | print a JSON document instead of text |
| `--no-color` | disable ANSI colours (also honours `NO_COLOR`) |
| `--no-fzf` | always use the plain prompt |
| `--refresh` | ignore the cached street catalogue |
| `--cache-ttl SECONDS` | how long the catalogue stays fresh (default 86400) |
| `--timeout SECONDS` | HTTP timeout (default 25) |
| `--timezone ZONE` | clock for dates and "now": `Europe/Kyiv`, `+02:00`, or `auto` (default; also `DTEK_TIMEZONE`) |
| `--base-url URL` | another host, useful for tests (`DTEK_BASE`) |
| `--version` | print the version |

Exit codes: `0` success, `1` error (network, unknown address, no data),
`130` cancelled by the user.

### JSON output

```json
{
  "address": { "city": "м. Одеса", "street": "вул. Дерибасівська", "house": "1",
               "label": "м. Одеса, вул. Дерибасівська, 1" },
  "queues": ["GPV3.1"],
  "source": { "updated": "18.11.2026 17:02", "today_key": "1794952800",
              "timezone": "UTC+02:00 (auto)" },
  "now": { "local_time": "21:16", "date": "18.11.2026" },
  "current": { "sub_type": null, "start": null, "end": null },
  "today": {
    "date": "18.11.2026",
    "queue": "GPV3.1",
    "intervals": [
      { "from": "00:00", "to": "08:00", "status": "yes",
        "status_text": "є світло", "outage": false }
    ]
  },
  "tomorrow": { "date": "19.11.2026", "queue": null, "intervals": [] },
  "announced": false
}
```

`status` is the raw provider code (`yes`, `no`, `first`, `second`, `maybe`,
`mfirst`, `msecond`); `outage` is `true` for anything that is not `yes`.
`announced: false` means the provider has not published tomorrow yet.

## Python API

The network layer is deliberately isolated. Copy
[`dtek_outages/api.py`](dtek_outages/api.py) alone if you only need requests:

```python
from dtek_outages.api import DtekClient

client = DtekClient()                 # timeout=25, custom base_url optional

streets = client.streets()            # {"м. Одеса": ["вул. Дерибасівська", ...]}
houses = client.houses("м. Одеса", "вул. Дерибасівська")
# [House(number='1', queues=('GPV3.1',), subtype='', start='', end='')]

house = client.house("м. Одеса", "вул. Дерибасівська", "1")

page = client.open()                  # session, CSRF token and both schedules
page.fact      # published schedule: {"today": ..., "update": ..., "data": {...}}
page.preset    # hour labels: {"time_zone": {"1": ["00-01", "00:00", "01:00"], ...}}
```

Turning raw data into intervals is also pure Python:

```python
from dtek_outages import schedule as sch

key = sch.today_key(page.fact)
day = sch.day_data(page.fact, key)
queue = sch.queue_for(day, house.queues)

for interval in sch.intervals(day, queue):
    start, end = sch.time_labels(page.preset, interval)
    print(start, end, interval.text)
```

A complete runnable example: [`examples/api_usage.py`](examples/api_usage.py).

## How it works

The site is a normal HTML page plus two JSON endpoints:

| Step | Request | What you get |
|---|---|---|
| 1 | `GET /ua/shutdowns` | HTML with `<meta name="csrf-token">`, a session cookie, and two inline JSON blobs: `DisconSchedule.fact` and `DisconSchedule.preset` |
| 2 | `POST /ua/ajax` `method=getStreets` | every settlement → its streets |
| 3 | `POST /ua/ajax` `method=getHomeNum` | houses of one street → their queue(s) |

AJAX calls need the cookie jar from step 1 plus
`X-CSRF-Token`, `X-Requested-With: XMLHttpRequest` and a form-encoded body.
The published schedule is **not** returned by AJAX — it is embedded in the
page as `DisconSchedule.fact = {...};`, which is why `open()` parses it out of
the HTML.

`fact` day keys are Unix timestamps of the provider's **local midnight**; hour keys are `"1"`
… `"24"` (00:00–01:00 … 23:00–24:00), and a missing hour means `yes`, exactly
as the provider's own page renders it. `preset.time_zone` maps an hour key to
its display labels (`"8" -> ["07-08", "07:00", "08:00"]`).

## Timezones

The provider publishes each day under a Unix timestamp of its **own local
midnight**, so the UTC offset is recoverable from the data: a key that lands on
22:00 UTC means the provider's offset is +02:00. By default (`--timezone auto`)
the tool derives that offset for every published day and uses it for calendar
dates and for "now", which makes the report correct on any machine, in any
timezone, and follows daylight-saving changes day by day. No zone name is
hardcoded.

Override it when needed:

```bash
dtek-outages --timezone Europe/Kyiv --city "м. Одеса" --street "" --house 1
dtek-outages --timezone +03:00 ...      # fixed offset
DTEK_TIMEZONE=Europe/Kyiv dtek-outages  # same, via the environment
```

An explicit zone must match the provider's own, otherwise day dates shift.
When the page carries no schedule at all (for example before the first
publication), the machine's own zone is used as a last resort. The resolved
zone is printed in JSON as `source.timezone`, e.g. `UTC+02:00 (auto)`.

Hour labels such as `08:00–11:00` always come from the provider's `preset`
and are displayed exactly as published.

## Caching

The large street catalogue is cached for a day so that repeat runs start fast:

| Platform | Path |
|---|---|
| Linux | `$XDG_CACHE_HOME/dtek-outages` or `~/.cache/dtek-outages` |
| macOS | `~/Library/Caches/dtek-outages` |
| Windows | `%LOCALAPPDATA%\dtek-outages` |

Override with `DTEK_CACHE_DIR`. When the network is down but a catalogue
copy exists, the tool warns on stderr and keeps working. The schedule itself
is never cached — it is always fetched fresh.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

## Notes and limitations

* Like the provider's page, the tool shows **plans**, not measurements. A
  published `yes` does not prove that power is actually on.
* Times are shown as the provider publishes them (Kyiv local in practice);
  the tool derives that zone itself instead of assuming one — see
  [Timezones](#timezones).
* Only the DTEK Odesa region (`dtek-oem.com.ua`) is supported.
* The site is unofficial and may change its markup or endpoints at any time.
* Be polite: the tool makes 2–3 requests per run and caches the catalogue.

## License

[MIT](LICENSE). Not affiliated with DTEK or DTEK-OEM; data belongs to them.
