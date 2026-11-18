"""Tests for the pure schedule logic and the inline-JSON extractor."""

from __future__ import annotations

import datetime as dt
import json
import unittest

from dtek_outages import schedule as sch
from dtek_outages.api import DtekError, inline_json

TODAY_TS = 1794952800  # 2026-11-18 00:00 Kyiv (EET)
TOMORROW_TS = TODAY_TS + 86400

PRESET = {
    "time_zone": {
        "1": ["00-01", "00:00", "01:00"],
        "8": ["07-08", "07:00", "08:00"],
        "9": ["08-09", "08:00", "09:00"],
        "11": ["10-11", "10:00", "11:00"],
        "12": ["11-12", "11:00", "12:00"],
        "24": ["23-24", "23:00", "24:00"],
    }
}


def make_fact(hours: dict[str, str], extra_day: dict | None = None) -> dict:
    data = {str(TODAY_TS): {"GPV3.1": hours}}
    if extra_day is not None:
        data[str(TOMORROW_TS)] = {"GPV3.1": extra_day}
    return {"today": TODAY_TS, "update": "18.11.2026 17:02", "data": data}


class IntervalTests(unittest.TestCase):
    def test_missing_hours_mean_power_on(self) -> None:
        day = {"GPV3.1": {"8": "no", "9": "no", "10": "no"}}
        result = sch.intervals(day, "GPV3.1")
        self.assertEqual(
            [(item.first_hour, item.last_hour, item.status) for item in result],
            [(1, 7, "yes"), (8, 10, "no"), (11, 24, "yes")],
        )
        self.assertEqual(result[1].text, "немає")
        self.assertTrue(result[1].is_outage)
        self.assertFalse(result[0].is_outage)

    def test_half_hour_statuses_are_kept_separate(self) -> None:
        day = {"GPV1.1": {"5": "first", "6": "second", "7": "no"}}
        result = sch.intervals(day, "GPV1.1")
        self.assertEqual(result[0].status, "yes")
        self.assertEqual(result[1].status, "first")
        self.assertEqual(result[2].status, "second")
        self.assertEqual(result[3].status, "no")
        self.assertEqual(result[1].text, "немає (перші 30 хв)")

    def test_time_labels_use_preset(self) -> None:
        interval = sch.Interval(8, 11, "no")
        self.assertEqual(sch.time_labels(PRESET, interval), ("07:00", "11:00"))

    def test_time_labels_fall_back_without_preset(self) -> None:
        interval = sch.Interval(8, 11, "no")
        self.assertEqual(sch.time_labels({}, interval), ("07:00", "11:00"))
        self.assertEqual(sch.time_labels({}, sch.Interval(1, 24, "yes"))[1], "24:00")

    def test_upcoming_skips_finished_intervals(self) -> None:
        day = {"GPV3.1": {"8": "no", "9": "no", "10": "no", "18": "no"}}
        at_noon = dt.datetime(2026, 11, 18, 12, 30, tzinfo=sch.kyiv_tz())
        nearest = sch.upcoming(day, "GPV3.1", at_noon)
        self.assertIsNotNone(nearest)
        self.assertEqual((nearest.first_hour, nearest.last_hour), (18, 18))

    def test_upcoming_none_when_nothing_left(self) -> None:
        day = {"GPV3.1": {"8": "no"}}
        late = dt.datetime(2026, 11, 18, 23, 30, tzinfo=sch.kyiv_tz())
        self.assertIsNone(sch.upcoming(day, "GPV3.1", late))

    def test_invalid_interval_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            sch.Interval(5, 4, "no")
        with self.assertRaises(ValueError):
            sch.Interval(0, 4, "no")
        with self.assertRaises(ValueError):
            sch.Interval(1, 25, "no")


class DayTests(unittest.TestCase):
    def test_day_map_and_today_key(self) -> None:
        fact = make_fact({}, extra_day={})
        self.assertEqual(sch.today_key(fact), str(TODAY_TS))
        days = sch.day_map(fact)
        self.assertEqual(set(days), {dt.date(2026, 11, 18), dt.date(2026, 11, 19)})

    def test_today_key_falls_back_to_earliest_day(self) -> None:
        fact = {"data": {str(TOMORROW_TS): {}, str(TODAY_TS): {}}}
        self.assertEqual(sch.today_key(fact), str(TODAY_TS))

    def test_queue_for_prefers_first_available(self) -> None:
        day = {"GPV2.1": {}, "GPV3.1": {}}
        self.assertEqual(sch.queue_for(day, ["GPV1.1", "GPV3.1"]), "GPV3.1")
        self.assertIsNone(sch.queue_for(day, ["GPV9.9"]))
        self.assertIsNone(sch.queue_for(None, ["GPV3.1"]))

    def test_kyiv_date_is_stable_for_midnight(self) -> None:
        self.assertEqual(sch.kyiv_date(TODAY_TS), dt.date(2026, 11, 18))
        self.assertEqual(sch.format_date(sch.kyiv_date(TODAY_TS)), "18.11.2026")


class InlineJsonTests(unittest.TestCase):
    def test_parses_object_inside_html(self) -> None:
        payload = {"data": {"1": {"GPV1.1": {"1": "yes"}}}, "update": "a }; b"}
        html = (
            "<html><script>var DisconSchedule.fact = "
            + json.dumps(payload, ensure_ascii=False)
            + ";\nvar x = 1;</script></html>"
        )
        self.assertEqual(inline_json(html, "fact"), payload)

    def test_missing_variable_reports_name(self) -> None:
        with self.assertRaises(DtekError) as caught:
            inline_json("<html></html>", "preset")
        self.assertIn("DisconSchedule.preset", str(caught.exception))

    def test_broken_json_reports_error(self) -> None:
        with self.assertRaises(DtekError):
            inline_json("DisconSchedule.fact = {oops};", "fact")


if __name__ == "__main__":
    unittest.main()
