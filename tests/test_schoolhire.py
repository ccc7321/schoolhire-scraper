import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import schoolhire as sh  # noqa: E402

SAMPLE = json.loads((ROOT / "get.json").read_text(encoding="utf-8"))


class FreePctTest(unittest.TestCase):
    def test_statuses(self):
        self.assertEqual(sh.free_pct({"busy": False, "text": "17:00-18:00 Available"}), 100)
        self.assertEqual(sh.free_pct({"busy": True, "text": "18:00-19:00 50% busy"}), 50)
        self.assertEqual(sh.free_pct({"busy": True, "text": "19:00-20:30 75% busy"}), 25)
        self.assertEqual(sh.free_pct({"busy": True, "className": "fully_booked",
                                      "text": "17:00-22:00 Booked"}), 0)
        self.assertIsNone(sh.free_pct({"busy": True, "text": "something new"}))


class ParseTest(unittest.TestCase):
    def test_sample_response(self):
        slots = sh.parse_calendar(SAMPLE, 17294)
        tue = [(s.start, s.end, s.free_pct) for s in slots if s.date == "2026-09-29"]
        self.assertEqual(tue, [("17:00", "18:00", 100), ("18:00", "19:00", 50),
                               ("19:00", "20:30", 25), ("20:30", "22:00", 0)])

    def test_other_facility_ignored(self):
        self.assertEqual(sh.parse_calendar(SAMPLE, 1), [])

    def test_facility_id_from_url(self):
        self.assertEqual(sh.facility_id_from_url(
            "https://schoolhire.co.uk/essex/castlegreen/basketball-court/43191?date="), 43191)


class WindowsTest(unittest.TestCase):
    def setUp(self):
        self.slots = sh.parse_calendar(SAMPLE, 17294)

    def fmt(self, windows):
        return [(d, sh.from_minutes(s), sh.from_minutes(e), p) for d, s, e, p in windows]

    def test_joins_adjacent_slots_at_least_half_free(self):
        got = self.fmt(sh.find_windows(self.slots, 50, 60))
        self.assertEqual(got, [
            ("2026-09-29", "17:00", "19:00", 50),
            ("2026-10-03", "09:00", "12:00", 50),
            ("2026-10-03", "14:00", "18:00", 100),
            ("2026-10-04", "09:00", "11:00", 50),
            ("2026-10-04", "13:00", "18:00", 50),
        ])

    def test_fully_free_only(self):
        got = self.fmt(sh.find_windows(self.slots, 100, 60))
        self.assertEqual(got, [("2026-09-29", "17:00", "18:00", 100),
                               ("2026-10-03", "09:00", "10:30", 100),
                               ("2026-10-03", "14:00", "18:00", 100),
                               ("2026-10-04", "09:00", "10:00", 100),
                               ("2026-10-04", "16:30", "18:00", 100)])

    def test_time_and_weekday_filters(self):
        got = self.fmt(sh.find_windows(self.slots, 50, 60, after="15:00", before="17:30",
                                       weekdays={6}))  # Sunday
        self.assertEqual(got, [("2026-10-04", "15:00", "17:30", 50)])

    def test_min_minutes(self):
        got = self.fmt(sh.find_windows(self.slots, 50, 30, after="17:00", weekdays={3}))
        self.assertEqual(got, [("2026-10-01", "17:00", "17:30", 50)])
        self.assertEqual(sh.find_windows(self.slots, 50, 60, weekdays={3}), [])


class SortTest(unittest.TestCase):
    def window(self, court, pell, colindale):
        return sh.Window(court=court, date="2026-10-01", start="18:00", end="19:00",
                         minutes=60, min_free_pct=100, price=20, court_size="half",
                         drive={"Pell St": {"min": pell, "miles": 1},
                                "Colindale": {"min": colindale, "miles": 1}},
                         notes="", link="")

    def test_drive_sort_by_origin(self):
        ws = [self.window("a", 10, 50), self.window("b", 30, 20)]
        order = lambda *args: [w.court for w in sorted(ws, key=sh.sort_key(*args))]
        self.assertEqual(order("drive"), ["a", "b"])  # first origin listed
        self.assertEqual(order("drive", "Pell St"), ["a", "b"])
        self.assertEqual(order("drive", "Colindale"), ["b", "a"])


if __name__ == "__main__":
    unittest.main()
