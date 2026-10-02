import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import brunel  # noqa: E402
import schoolhire as sh  # noqa: E402

SAMPLE = json.loads((ROOT / "brunel.json").read_text(encoding="utf-8"))
COURT = {"name": "Brunel Netball Hall", "source": "brunel", "activity_id": "NHBASKETBALL",
         "url": brunel.BOOK_URL}


class UkTimeTest(unittest.TestCase):
    def test_bst_and_gmt(self):
        utc = dt.timezone.utc
        self.assertEqual(brunel.uk_time(dt.datetime(2026, 9, 29, 17, 30, tzinfo=utc)),
                         dt.datetime(2026, 9, 29, 18, 30))
        # clocks go back at 01:00 UTC on Sun 25 Oct 2026
        self.assertEqual(brunel.uk_time(dt.datetime(2026, 10, 25, 0, 59, tzinfo=utc)).hour, 1)
        self.assertEqual(brunel.uk_time(dt.datetime(2026, 10, 25, 1, 0, tzinfo=utc)).hour, 1)
        self.assertEqual(brunel.uk_time(dt.datetime(2026, 12, 1, 18, 0, tzinfo=utc)).hour, 18)


class ParseTest(unittest.TestCase):
    def test_one_slot_per_session_in_uk_time(self):
        slots = brunel.parse_sessions(SAMPLE, "NHBASKETBALL")
        tue = [(s.start, s.end, s.free_pct) for s in slots if s.date == "2026-09-29"]
        self.assertEqual(tue[:3], [("07:30", "08:30", 100), ("08:30", "09:30", 100),
                                   ("09:30", "10:30", 0)])
        self.assertEqual(tue[-1], ("21:30", "22:25", 0))  # last session keeps its real end

    def test_activity_filter(self):
        half = brunel.parse_sessions(SAMPLE, "SHBASKHALF12")
        self.assertEqual(half[0].date, "2026-09-28")
        self.assertEqual(brunel.parse_sessions(SAMPLE, "SHBASKHALF34"), [])

    def test_windows_from_fixture(self):
        slots = sh.load_court_slots(COURT, dt.date(2026, 9, 28), dt.date(2026, 10, 4),
                                    fixture=ROOT / "get.json")
        ws = sh.court_windows(COURT, slots, 50, 60)
        self.assertEqual([(w.date, w.start, w.end) for w in ws][:3], [
            ("2026-09-29", "07:30", "09:30"), ("2026-09-30", "07:30", "12:30"),
            ("2026-10-01", "07:30", "09:30")])
        self.assertEqual(ws[0].link, brunel.BOOK_URL + "?date=2026-09-29")


if __name__ == "__main__":
    unittest.main()
