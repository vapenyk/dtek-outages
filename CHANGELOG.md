# Changelog

## 1.1.0

* The timezone is no longer hardcoded. Day timestamps are provider-local
  midnights, so their UTC offset is derived from the data (`--timezone auto`,
  the default) and used for calendar dates and "now". Explicit zones are
  accepted as IANA names (`Europe/Kyiv`) or fixed offsets (`+02:00`) via
  `--timezone` / `DTEK_TIMEZONE`.
* JSON: `now.kyiv_time` renamed to `now.local_time`, and `source.timezone` now
  reports the resolved zone, e.g. `UTC+02:00 (auto)`.
* `Clock`, `ZoneError` and `resolve_clock` are exported from the package.

## 1.0.0

* First release: interactive address picker, text and JSON reports, cached
  street catalogue, standard library only.
