import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import courts as store  # noqa: E402
import drive  # noqa: E402
import schoolhire as sh  # noqa: E402

DAGENHAM = "https://schoolhire.co.uk/Dagenham/dagenham-park-leisure-centre/basketball-court/17294"
BOW = "https://schoolhire.co.uk/london-tower-hamlets/bow-school/basketball-court/4425"


class Response:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body or {}

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")


class FakeSession:
    """postcodes.io and TomTom, answering from a few made-up places."""

    def __init__(self, status=200):
        self.calls, self.status = [], status

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params or {}))
        if self.status != 200:
            return Response(self.status)
        if url.startswith(drive.POSTCODES_API):
            pc = url.rsplit("/", 1)[1].upper()
            return Response(200, {"result": {"latitude": len(pc), "longitude": -0.1}}) \
                if pc != "ZZ99ZZ" else Response(404)
        if "/geocode/" in url:
            return Response(200, {"results": [{"position": {"lat": 51.5, "lon": -0.07}}]})
        if "/calculateRoute/" in url:
            return Response(200, {"routes": [{"summary": {
                "travelTimeInSeconds": 37 * 60 - 20, "lengthInMeters": 19312}}]})
        raise AssertionError(url)


class DepartureTest(unittest.TestCase):
    def test_parse(self):
        self.assertIsNone(drive.parse_depart("now"))
        self.assertIsNone(drive.parse_depart(""))
        self.assertEqual(drive.parse_depart(" Tuesday  8:05 "), ("tue", "08:05"))
        for bad in ("tue", "18:00", "tue 25:00", "xyz 18:00"):
            with self.assertRaises(drive.DriveError, msg=bad):
                drive.parse_depart(bad)

    def test_next_departure_is_in_the_future(self):
        now = dt.datetime(2026, 10, 27, 17, 55)  # a Tuesday
        self.assertEqual(drive.next_departure("tue", "18:00", now), dt.datetime(2026, 11, 3, 18, 0))
        self.assertEqual(drive.next_departure("tue", "19:00", now), dt.datetime(2026, 10, 27, 19, 0))
        self.assertEqual(drive.next_departure("mon", "18:00", now), dt.datetime(2026, 11, 2, 18, 0))


class EstimateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.patches = [mock.patch.object(store, "PATH", tmp / "courts.json"),
                        mock.patch.object(drive, "SETTINGS", tmp / "settings.json"),
                        mock.patch.object(drive, "CALL_GAP", 0),
                        mock.patch.dict(os.environ, {}, clear=False)]
        for p in self.patches:
            p.start()
        os.environ.pop("TOMTOM_API_KEY", None)
        drive._places.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def court(self, url):
        return next(c for c in store.load()["groups"][0]["courts"] if c["url"] == url)

    def test_key_is_saved_but_never_shown(self):
        self.assertEqual(drive.key_status()["tomtom_key_set"], False)
        with self.assertRaises(drive.DriveError):
            drive.save_key("not a key!")
        drive.save_key(" abcdefghij1234 ")
        self.assertEqual(drive.key_status(), {"tomtom_key_set": True, "key_hint": "…1234",
                                              "from_env": False})
        self.assertEqual(json.loads(drive.SETTINGS.read_text())["tomtom_key"], "abcdefghij1234")
        drive.save_key("")
        self.assertFalse(drive.key_status()["tomtom_key_set"])

    def test_needs_a_key_and_a_starting_place(self):
        with self.assertRaisesRegex(drive.DriveError, "key"):
            drive.estimate_group("east-london", "now", session=FakeSession())
        drive.save_key("abcdefghij1234")
        with self.assertRaisesRegex(drive.DriveError, "driving from"):
            drive.estimate_group("east-london", "now", session=FakeSession())

    def test_estimates_keep_your_guesses(self):
        drive.save_key("abcdefghij1234")
        store.update_group("east-london", {"from": "Pell St, London"})
        store.edit_court("east-london", BOW, {"drive_min": 21})
        session = FakeSession()
        now = dt.datetime(2026, 10, 27, 12, 0)
        res = drive.estimate_group("east-london", "tue 18:00", session=session, now=now)

        self.assertEqual(res["skipped"], ["Bow School"])
        self.assertEqual(len(res["updated"]), 6)
        self.assertEqual((res["failed"], res["depart"]), ({}, "Tue 18:00"))
        self.assertEqual((self.court(BOW)["drive_min"], self.court(BOW)["drive_source"]), (21, "guess"))
        d = self.court(DAGENHAM)
        self.assertEqual((d["drive_min"], d["drive_miles"], d["drive_source"], d["drive_when"]),
                         (37, 12.0, "tomtom", "Tue 18:00"))
        self.assertEqual(store.load()["groups"][0]["depart"], "tue 18:00")

        # "Pell St" isn't a postcode so TomTom's geocoder found it; courts use postcodes.io
        urls = [u for u, _ in session.calls]
        self.assertEqual(sum("/geocode/" in u for u in urls), 1)
        self.assertTrue(any(u.endswith("/RM109QH") for u in urls))
        route_params = next(p for u, p in session.calls if "/calculateRoute/" in u)
        self.assertEqual((route_params["departAt"], route_params["traffic"], route_params["key"]),
                         ("2026-10-27T18:00:00", "true", "abcdefghij1234"))

        # shown as an estimate, not a guess
        drives = next(c for c in store.courts_in(store.load()) if c["url"] == DAGENHAM)["drive"]
        self.assertEqual(drives, [{"from": "Pell St, London", "min": 37, "miles": 12.0,
                                   "when": "Tue 18:00"}])
        self.assertEqual(sh.fmt_drive(drives), "37m from Pell St, London (TomTom Tue 18:00)")

        # typing over an estimate makes it your guess again
        store.edit_court("east-london", DAGENHAM, {"drive_min": 45})
        d = self.court(DAGENHAM)
        self.assertEqual((d["drive_min"], d["drive_source"], "drive_miles" in d), (45, "guess", False))

        # replace=True overwrites guesses too; "now" sends no departAt
        session = FakeSession()
        res = drive.estimate_group("east-london", "now", replace_guesses=True, session=session)
        self.assertEqual((len(res["updated"]), res["skipped"], res["depart"]), (7, [], "now"))
        self.assertNotIn("departAt", next(p for u, p in session.calls if "/calculateRoute/" in u))

    def test_one_court_failing_doesnt_stop_the_others(self):
        drive.save_key("abcdefghij1234")
        store.update_group("east-london", {"from": "E1 1AA"})
        data = store.load()
        data["groups"][0]["courts"][0]["postcode"] = "ZZ9 9ZZ"  # postcodes.io doesn't know it

        class NoGeocode(FakeSession):
            def get(self, url, params=None, timeout=None):
                if "/geocode/" in url:
                    self.calls.append((url, params))
                    return Response(200, {"results": []})
                return super().get(url, params, timeout)
        store.save(data)
        res = drive.estimate_group("east-london", "now", session=NoGeocode())
        self.assertEqual(list(res["failed"]), ["Bow School"])
        self.assertIn("postcode", res["failed"]["Bow School"])
        self.assertEqual(len(res["updated"]), 6)

    def test_bad_key_stops_straight_away(self):
        drive.save_key("abcdefghij1234")
        store.update_group("east-london", {"from": "Pell St"})
        session = FakeSession(status=403)
        with self.assertRaisesRegex(drive.DriveError, "refused the key"):
            drive.estimate_group("east-london", "now", session=session)
        self.assertEqual(len(session.calls), 1)


if __name__ == "__main__":
    unittest.main()
