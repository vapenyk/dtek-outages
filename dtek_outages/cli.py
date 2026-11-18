"""Command line interface: pick an address and print its outage schedule."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from . import schedule as sch
from .api import DtekClient, DtekError, House
from .report import json_report, text_report
from .select import SelectionCancelled, choose

DEFAULT_CACHE_TTL = 24 * 60 * 60  # one day, like the site's own catalogue

UKRAINIAN = "uk_UA.UTF-8"


# -- cache -----------------------------------------------------------------
def cache_root() -> Path:
    """Per-platform cache directory (``XDG_CACHE_HOME`` aware)."""

    override = os.environ.get("DTEK_CACHE_DIR")
    if override:
        return Path(override).expanduser()

    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "dtek-outages"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "dtek-outages"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or Path.home()
        return Path(base) / "dtek-outages"
    return Path.home() / ".cache" / "dtek-outages"


def _read_streets(path: Path) -> dict[str, list[str]] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    streets = payload.get("streets") if isinstance(payload, dict) else None
    return streets if isinstance(streets, dict) else None


def _write_streets(path: Path, streets: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".streets-",
        suffix=".json",
        delete=False,
    )
    try:
        with handle:
            json.dump({"streets": streets}, handle, ensure_ascii=False)
            handle.write("\n")
        os.replace(handle.name, path)
        os.chmod(path, 0o644)
    except OSError:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def load_streets(
    client: DtekClient,
    path: Path,
    ttl: int = DEFAULT_CACHE_TTL,
    refresh: bool = False,
) -> dict[str, list[str]]:
    """Street catalogue, cached on disk; falls back to a stale copy offline."""

    cached = None if refresh else _read_streets(path)
    if cached is not None:
        try:
            fresh = time.time() - path.stat().st_mtime < ttl
        except OSError:
            fresh = False
        if fresh:
            return cached

    try:
        streets = client.streets()
    except DtekError as exc:
        if cached is not None:
            print(
                f"Не вдалося оновити довідник ({exc}); використовую збережений.",
                file=sys.stderr,
            )
            return cached
        raise

    try:
        _write_streets(path, streets)
    except OSError as exc:
        print(f"Не вдалося зберегти кеш у {path}: {exc}", file=sys.stderr)
    return streets


# -- address picking -------------------------------------------------------
def _suggest(value: str, options: Sequence[str]) -> str:
    close = difflib.get_close_matches(value, options, n=3, cutoff=0.6)
    return f" Можливо: {', '.join(close)}." if close else ""


def _match(value: str, options: Sequence[str]) -> str | None:
    if value in options:
        return value
    folded = value.casefold()
    for option in options:
        if option.casefold() == folded:
            return option
    return None


def pick_city(
    streets: dict[str, list[str]], requested: str | None, use_fzf: bool
) -> str:
    names = sorted(streets)
    if requested is not None:
        matched = _match(requested, names)
        if matched is None:
            raise DtekError(
                f"Невідомий населений пункт «{requested}»." + _suggest(requested, names)
            )
        return matched
    return choose(
        "Населений пункт >",
        names,
        header="Введіть назву, Enter — вибрати",
        use_fzf=use_fzf,
    )


def pick_street(
    streets: Sequence[str], requested: str | None, city: str, use_fzf: bool
) -> str:
    if not streets:
        raise DtekError(f"Немає вулиць для «{city}»")
    if len(streets) == 1 and not streets[0]:
        return ""  # settlement without streets

    if requested is not None:
        if requested == "":
            return ""
        matched = _match(requested, streets)
        if matched is None:
            raise DtekError(
                f"Невідома вулиця «{requested}» у «{city}»."
                + _suggest(requested, streets)
            )
        return matched
    return choose(
        "Вулиця >",
        list(streets),
        header=f"Населений пункт: {city}",
        use_fzf=use_fzf,
    )


def pick_house(
    houses: Sequence[House],
    requested: str | None,
    city: str,
    street: str,
    use_fzf: bool,
) -> House:
    if requested is not None:
        matched = _match(requested, [house.number for house in houses])
        if matched is not None:
            return next(house for house in houses if house.number == matched)
        raise DtekError(
            f"Немає будинку «{requested}»."
            + _suggest(requested, [house.number for house in houses])
        )

    if len(houses) == 1:
        return houses[0]

    lines = [f"{house.number}\t{house.queues_text}" for house in houses]
    where = ", ".join(part for part in (city, street) if part)
    chosen = choose(
        "Номер будинку >",
        lines,
        header=f"Будинок | черга(и)   ({where})",
        extra=["--delimiter=\t", "--with-nth=1,2"],
        use_fzf=use_fzf,
    )
    number = chosen.split("\t", 1)[0]
    return next(house for house in houses if house.number == number)


# -- entry point -----------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dtek-outages",
        description=(
            "Графік відключень ДТЕК (ООЕМ) за адресою: населений пункт → вулиця → будинок."
        ),
        epilog=(
            "Приклади:\n"
            "  dtek-outages\n"
            "  dtek-outages --city 'Авангардівська ТГ' --street 'Без вулиці' --house 77\n"
            "  dtek-outages --city 'м. Одеса' --street 'вул. Дерибасівська' --house 1 --json\n"
            "\n"
            "Джерело даних: https://www.dtek-oem.com.ua/ua/shutdowns"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--city", help="населений пункт (без інтерактивного вибору)")
    parser.add_argument(
        "--street",
        help="вулиця; порожній рядок --street '' для населених пунктів без вулиць",
    )
    parser.add_argument("--house", help="номер будинку")
    parser.add_argument(
        "--json", action="store_true", help="вивести дані у JSON замість тексту"
    )
    parser.add_argument(
        "--no-color", action="store_true", help="вимкнути кольори та ANSI-коди"
    )
    parser.add_argument(
        "--no-fzf", action="store_true", help="не використовувати fzf навіть якщо він є"
    )
    parser.add_argument(
        "--refresh", action="store_true", help="оновити кеш довідника адрес"
    )
    parser.add_argument(
        "--timezone",
        metavar="ZONE",
        default=None,
        help=(
            "часова зона для дат і «зараз»: IANA-назва (Europe/Kyiv), зсув "
            "(+02:00) або auto. Типово auto — зсув визначається з даних сайту "
            "(env: DTEK_TIMEZONE)"
        ),
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=DEFAULT_CACHE_TTL,
        metavar="SECONDS",
        help=f"скільки секунд вважати кеш свіжим (типово {DEFAULT_CACHE_TTL})",
    )
    parser.add_argument(
        "--timeout", type=float, default=25.0, metavar="SECONDS", help="таймаут запиту"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("DTEK_BASE", "https://www.dtek-oem.com.ua"),
        help="інший хост, наприклад для тестів (env: DTEK_BASE)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _use_color(args: argparse.Namespace) -> bool:
    if args.no_color or os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


def _run(args: argparse.Namespace) -> int:
    client = DtekClient(base_url=args.base_url, timeout=args.timeout)
    streets = load_streets(
        client,
        cache_root() / "streets.json",
        ttl=args.cache_ttl,
        refresh=args.refresh,
    )

    city = pick_city(streets, args.city, not args.no_fzf)
    street = pick_street(
        streets.get(city) or [], args.street, city, not args.no_fzf
    )

    houses = client.houses(city, street)
    if not houses:
        place = ", ".join(part for part in (city, street) if part)
        raise DtekError(f"Для адреси «{place}» немає даних")

    house = pick_house(houses, args.house, city, street, not args.no_fzf)
    page = client.open()
    clock = sch.resolve_clock(page.fact, args.timezone)

    if args.json:
        payload: dict[str, Any] = json_report(
            city=city,
            street=street,
            house=house,
            queues=house.queues,
            fact=page.fact,
            preset=page.preset,
            clock=clock,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    lines = text_report(
        city=city,
        street=street,
        house=house,
        queues=house.queues,
        fact=page.fact,
        preset=page.preset,
        clock=clock,
        color=_use_color(args),
    )
    print("\n".join(lines))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except SelectionCancelled:
        return 130
    except sch.ZoneError as exc:
        print(f"Помилка: {exc}", file=sys.stderr)
        return 1
    except DtekError as exc:
        print(f"Помилка: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
    except BrokenPipeError:  # `dtek-outages | head`
        # Keep Python from complaining about the closed pipe at shutdown.
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
