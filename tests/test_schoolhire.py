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
    def window(self, court, price, date="2026-10-01", drive=()):
        return sh.Window(court=court, date=date, start="18:00", end="19:00", minutes=60,
                         min_free_pct=100, price=price, court_size="half", notes="", link="",
                         drive=[{"from": f, "min": m} for f, m in drive])

    def test_price_sort_puts_unknown_prices_last(self):
        ws = [self.window("a", None), self.window("b", 30), self.window("c", 20, "2026-10-02")]
        order = lambda sort: [w.court for w in sorted(ws, key=sh.SORT_KEYS[sort])]
        self.assertEqual(order("price"), ["c", "b", "a"])
        self.assertEqual(order("date"), ["a", "b", "c"])

    def test_drive_sort_uses_the_shortest_guess_and_puts_unknown_last(self):
        ws = [self.window("a", 20), self.window("b", 20, drive=[("Home", 40), ("Work", 15)]),
              self.window("c", 20, drive=[("Home", 25)])]
        self.assertEqual([w.court for w in sorted(ws, key=sh.SORT_KEYS["drive"])], ["b", "c", "a"])
        self.assertEqual(sh.fmt_drive(ws[1].drive), "~40m from Home, ~15m from Work")


class GroupTest(unittest.TestCase):
    groups = {"groups": [
        {"id": "east-london", "name": "East London", "courts": [{"name": "A", "url": "u1"}]},
        {"id": "x1", "name": "Weekend", "courts": [{"name": "A", "url": "u1"},
                                                   {"name": "B", "url": "u2"}]}]}

    def test_group_by_name_or_id(self):
        names = lambda g: [c["name"] for c in sh.group_courts(self.groups, g)]
        self.assertEqual(names("east london"), ["A"])
        self.assertEqual(names("X1"), ["A", "B"])
        self.assertEqual(names(None), ["A", "B"])  # every court once
        with self.assertRaises(SystemExit):
            sh.group_courts(self.groups, "nope")


if __name__ == "__main__":
    unittest.main()
