"""Tests for the CLI helpers and the two report formats (no network)."""

from __future__ import annotations

import datetime as dt
import unittest

from dtek_outages import schedule as sch
from dtek_outages.api import DtekError, House
from dtek_outages.cli import pick_city, pick_house, pick_street
from dtek_outages.report import address_label, json_report, text_report

TODAY_TS = 1794952800
TOMORROW_TS = TODAY_TS + 86400

PRESET = {
    "time_zone": {
        "1": ["00-01", "00:00", "01:00"],
        "8": ["07-08", "07:00", "08:00"],
        "9": ["08-09", "08:00", "09:00"],
        "10": ["09-10", "09:00", "10:00"],
        "11": ["10-11", "10:00", "11:00"],
        "12": ["11-12", "11:00", "12:00"],
        "24": ["23-24", "23:00", "24:00"],
    }
}

STREETS = {"м. Одеса": ["вул. Дерибасівська", "вул. Преображенська"], "с. Тест": [""]}


def fact(hours: dict[str, str] | None = None, tomorrow: dict | None = None) -> dict:
    data: dict = {str(TODAY_TS): {"GPV3.1": hours or {}}}
    if tomorrow is not None:
        data[str(TOMORROW_TS)] = {"GPV3.1": tomorrow}
    return {"today": TODAY_TS, "update": "18.11.2026 17:02", "data": data}


class PickingTests(unittest.TestCase):
    def test_exact_city(self) -> None:
        self.assertEqual(pick_city(STREETS, "м. Одеса", False), "м. Одеса")

    def test_city_is_case_insensitive(self) -> None:
        self.assertEqual(pick_city(STREETS, "М. ОДЕСА", False), "м. Одеса")

    def test_unknown_city_suggests_alternative(self) -> None:
        with self.assertRaises(DtekError) as caught:
            pick_city(STREETS, "Одесса", False)
        self.assertIn("м. Одеса", str(caught.exception))

    def test_street_without_streets(self) -> None:
        self.assertEqual(pick_street([""], None, "с. Тест", False), "")

    def test_unknown_street(self) -> None:
        with self.assertRaises(DtekError):
            pick_street(STREETS["м. Одеса"], "вул. Нема", "м. Одеса", False)

    def test_house_by_number(self) -> None:
        houses = [House("1", ("GPV1.1",)), House("2", ("GPV2.2",))]
        self.assertEqual(pick_house(houses, "2", "місто", "вулиця", False).queues, ("GPV2.2",))

    def test_single_house_needs_no_prompt(self) -> None:
        houses = [House("7", ("GPV3.1",))]
        self.assertEqual(pick_house(houses, None, "місто", "вулиця", False).number, "7")

    def test_unknown_house(self) -> None:
        with self.assertRaises(DtekError):
            pick_house([House("1", ())], "9", "місто", "вулиця", False)


class ReportTests(unittest.TestCase):
    noon = dt.datetime(2026, 11, 18, 12, 30, tzinfo=sch.kyiv_tz())

    def test_address_label_skips_empty_street(self) -> None:
        self.assertEqual(address_label("с. Тест", "", "5"), "с. Тест, 5")
        self.assertEqual(address_label("м. Одеса", "вул. Х", "5"), "м. Одеса, вул. Х, 5")

    def test_text_report_today_and_announced_tomorrow(self) -> None:
        page = fact({"8": "no", "9": "no", "10": "no"}, tomorrow={"20": "no"})
        lines = text_report(
            city="м. Одеса",
            street="вул. Дерибасівська",
            house=House("1", ("GPV3.1",)),
            queues=["GPV3.1"],
            fact=page,
            preset=PRESET,
            now=self.noon,
            color=False,
        )
        text = "\n".join(lines)
        self.assertIn("м. Одеса, вул. Дерибасівська, 1", text)
        self.assertIn("Черга: GPV3.1", text)
        self.assertIn("07:00–10:00   немає", text)
        self.assertIn("Графік на завтра (19.11.2026, GPV3.1):", text)
        self.assertIn("Найближче завтра: з 19:00", text)
        self.assertIn("Оновлено: 18.11.2026 17:02", text)

    def test_text_report_without_tomorrow_data(self) -> None:
        lines = text_report(
            city="м. Одеса",
            street="",
            house=House("1", ("GPV3.1",)),
            queues=["GPV3.1"],
            fact=fact({"8": "no"}),
            preset=PRESET,
            now=self.noon,
            color=False,
        )
        self.assertIn("Укренерго", "\n".join(lines))

    def test_text_report_respects_no_color(self) -> None:
        lines = text_report(
            city="м. Одеса",
            street="",
            house=House("1", ("GPV3.1",)),
            queues=["GPV3.1"],
            fact=fact({"8": "no"}),
            preset=PRESET,
            now=self.noon,
            color=False,
        )
        self.assertNotIn("\x1b[", "\n".join(lines))

    def test_text_report_colors_statuses(self) -> None:
        lines = text_report(
            city="м. Одеса",
            street="",
            house=House("1", ("GPV3.1",)),
            queues=["GPV3.1"],
            fact=fact({"8": "no"}),
            preset=PRESET,
            now=self.noon,
            color=True,
        )
        self.assertIn("\x1b[31mнемає\x1b[0m", "\n".join(lines))

    def test_json_report_shape(self) -> None:
        payload = json_report(
            city="м. Одеса",
            street="",
            house=House("1", ("GPV3.1",)),
            queues=["GPV3.1"],
            fact=fact({"8": "no"}, tomorrow={"20": "no"}),
            preset=PRESET,
            now=self.noon,
        )
        self.assertEqual(payload["address"]["label"], "м. Одеса, 1")
        self.assertEqual(payload["today"]["intervals"][1]["status"], "no")
        self.assertEqual(payload["today"]["intervals"][1]["from"], "07:00")
        self.assertTrue(payload["announced"])
        self.assertEqual(payload["current"]["sub_type"], None)

    def test_detected_clock_is_reported(self) -> None:
        payload = json_report(
            city="м. Одеса",
            street="",
            house=House("1", ("GPV3.1",)),
            queues=["GPV3.1"],
            fact=fact({}),
            preset=PRESET,
            now=self.noon,
        )
        self.assertEqual(payload["source"]["timezone"], "UTC+02:00 (auto)")
        self.assertEqual(payload["today"]["date"], "18.11.2026")

    def test_explicit_clock_changes_the_dates(self) -> None:
        page = fact({})
        utc = json_report(
            city="м. Одеса",
            street="",
            house=House("1", ("GPV3.1",)),
            queues=["GPV3.1"],
            fact=page,
            preset=PRESET,
            clock=sch.resolve_clock(page, requested="UTC"),
            now=self.noon,
        )
        self.assertEqual(utc["source"]["timezone"], "UTC")
        # The key is 2026-11-17 22:00 UTC, i.e. already the 17th in UTC.
        self.assertEqual(utc["today"]["date"], "17.11.2026")

    def test_json_report_without_tomorrow(self) -> None:
        payload = json_report(
            city="м. Одеса",
            street="",
            house=House("1", ("GPV3.1",)),
            queues=["GPV3.1"],
            fact=fact({}),
            preset=PRESET,
            now=self.noon,
        )
        self.assertFalse(payload["announced"])
        self.assertEqual(payload["tomorrow"]["intervals"], [])


if __name__ == "__main__":
    unittest.main()
