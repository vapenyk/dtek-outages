# dtek-outages

Неофіційний консольний клієнт для **графіків відключень ДТЕК Одеса (ДТЕК-ОЕМ)**.
Обираєте населений пункт → вулицю → будинок і отримуєте опублікований графік
для своєї адреси, номер черги та поточне повідомлення провайдера.

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

* **Без залежностей** — лише стандартна бібліотека Python 3.9+.
* **Linux, macOS і \*BSD** — жодних GNU-only викликів `date`, `grep -P` чи `stat`.
* **fzf необов'язковий** — без нього буде звичайний нумерований вибір.
* **Мережевий шар можна скопіювати**: усі запити живуть в одному файлі
  [`dtek_outages/api.py`](dtek_outages/api.py) без сторонніх імпортів.
* **JSON-вивід** для скриптів, барів і дашбордів.
* **29 юніт-тестів**, мережа для них не потрібна.

English version: [README.md](README.md).

## Що потрібно

| Компонент | Потрібно | Примітка |
|---|---|---|
| Python | 3.9 або новіший | `python3 --version` |
| `fzf` | необов'язково | зручніший вибір; `brew install fzf`, `pkg install fzf`, `apt install fzf` |
| Мережа | так | `https://www.dtek-oem.com.ua` |
| `tzdata` | зазвичай уже є | для київського часу; інакше використається локальний |

## Встановлення

Запуск просто з клону репозиторію:

```bash
git clone https://github.com/vapenyk/dtek-outages.git
cd dtek-outages
./dtek-outages
```

Встановлення як команди (будь-який варіант):

```bash
pipx install .            # ізольовано, рекомендовано
python3 -m pip install .  # у поточне середовище
make install              # те саме, що python3 -m pip install --user .
```

Далі:

```bash
dtek-outages
```

## Використання

```bash
# інтерактивно: населений пункт -> вулиця -> будинок
dtek-outages

# без інтерактиву
dtek-outages --city "Авангардівська ТГ" --street "Без вулиці" --house 77

# населений пункт без поділу на вулиці
dtek-outages --city "с. Тест" --street "" --house 5

# для скриптів
dtek-outages --city "м. Одеса" --street "вул. Дерибасівська" --house 1 --json
```

### Опції

| Опція | Значення |
|---|---|
| `--city NAME` | населений пункт; пропускає вибір міста |
| `--street NAME` | вулиця; `''` для населених пунктів без вулиць |
| `--house NUMBER` | номер будинку (наприклад `77`, `/зд 15`) |
| `--json` | вивести JSON замість тексту |
| `--no-color` | вимкнути кольори (також поважає `NO_COLOR`) |
| `--no-fzf` | завжди використовувати простий вибір |
| `--refresh` | не використовувати кеш довідника адрес |
| `--cache-ttl SECONDS` | скільки секунд кеш вважається свіжим (типово 86400) |
| `--timeout SECONDS` | таймаут HTTP-запиту (типово 25) |
| `--base-url URL` | інший хост, корисно для тестів (`DTEK_BASE`) |
| `--version` | версія |

Коди виходу: `0` — успіх, `1` — помилка (мережа, невідома адреса, немає
даних), `130` — скасовано користувачем.

### JSON

```json
{
  "address": { "city": "м. Одеса", "street": "вул. Дерибасівська", "house": "1",
               "label": "м. Одеса, вул. Дерибасівська, 1" },
  "queues": ["GPV3.1"],
  "source": { "updated": "18.11.2026 17:02", "today_key": "1794952800",
              "timezone": "Europe/Kyiv" },
  "now": { "kyiv_time": "21:16", "date": "18.11.2026" },
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

`status` — «сирий» код провайдера (`yes`, `no`, `first`, `second`, `maybe`,
`mfirst`, `msecond`); `outage` — `true` для всього, що не `yes`.
`announced: false` означає, що графік на завтра ще не опубліковано.

## Python API

Мережевий шар навмисно відокремлений. Якщо потрібні лише запити, достатньо
скопіювати [`dtek_outages/api.py`](dtek_outages/api.py):

```python
from dtek_outages.api import DtekClient

client = DtekClient()                 # timeout=25, можна свій base_url

streets = client.streets()            # {"м. Одеса": ["вул. Дерибасівська", ...]}
houses = client.houses("м. Одеса", "вул. Дерибасівська")
# [House(number='1', queues=('GPV3.1',), subtype='', start='', end='')]

house = client.house("м. Одеса", "вул. Дерибасівська", "1")

page = client.open()                  # сесія, CSRF-токен і обидва графіки
page.fact      # опублікований графік: {"today": ..., "update": ..., "data": {...}}
page.preset    # підписи годин: {"time_zone": {"1": ["00-01", "00:00", "01:00"], ...}}
```

Перетворення сирих даних на інтервали — теж чистий Python:

```python
from dtek_outages import schedule as sch

key = sch.today_key(page.fact)
day = sch.day_data(page.fact, key)
queue = sch.queue_for(day, house.queues)

for interval in sch.intervals(day, queue):
    start, end = sch.time_labels(page.preset, interval)
    print(start, end, interval.text)
```

Повний робочий приклад: [`examples/api_usage.py`](examples/api_usage.py).

## Як це працює

Сайт — це звичайна HTML-сторінка плюс два JSON-ендпоінти:

| Крок | Запит | Що отримуємо |
|---|---|---|
| 1 | `GET /ua/shutdowns` | HTML із `<meta name="csrf-token">`, cookie сесії та двома вбудованими JSON: `DisconSchedule.fact` і `DisconSchedule.preset` |
| 2 | `POST /ua/ajax` `method=getStreets` | усі населені пункти → їхні вулиці |
| 3 | `POST /ua/ajax` `method=getHomeNum` | будинки однієї вулиці → їхні черги |

Для AJAX потрібні cookie з кроку 1, заголовки `X-CSRF-Token`,
`X-Requested-With: XMLHttpRequest` і form-urlencoded тіло.
Сам графік AJAX **не** повертає — він вбудований у сторінку як
`DisconSchedule.fact = {...};`, тому `open()` дістає його з HTML.

Ключі днів у `fact` — це Unix-мітки **київської півночі**; ключі годин — `"1"`
… `"24"` (00:00–01:00 … 23:00–24:00), і відсутня година означає `yes` — саме
так це показує сторінка провайдера. `preset.time_zone` перетворює ключ години
на підписи (`"8" -> ["07-08", "07:00", "08:00"]`).

## Кеш

Великий довідник вулиць кешується на добу, щоб повторні запуски були швидкими:

| Платформа | Шлях |
|---|---|
| Linux | `$XDG_CACHE_HOME/dtek-outages` або `~/.cache/dtek-outages` |
| macOS | `~/Library/Caches/dtek-outages` |
| Windows | `%LOCALAPPDATA%\dtek-outages` |

Перевизначити можна через `DTEK_CACHE_DIR`. Якщо мережа недоступна, але копія
довідника є, інструмент попередить у stderr і продовжить роботу. Сам графік
не кешується — він завжди завантажується свіжим.

## Тести

```bash
python3 -m unittest discover -s tests -t .
```

## Обмеження

* Як і сторінка провайдера, інструмент показує **план**, а не вимірювання.
  Опубліковане `yes` не доводить, що світло справді є.
* Час завжди київський, незалежно від часового поясу вашого комп'ютера.
* Підтримується лише регіон ДТЕК Одеса (`dtek-oem.com.ua`).
* Сайт неофіційний і може змінити розмітку чи ендпоінти будь-коли.
* Будьте ввічливі: один запуск робить 2–3 запити, а довідник кешується.

## Ліцензія

[MIT](LICENSE). Проєкт не пов'язаний з ДТЕК чи ДТЕК-ОЕМ; дані належать їм.
