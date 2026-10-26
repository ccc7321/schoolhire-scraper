import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import app as court_app
    import courts as store
except ImportError:  # flask not installed
    court_app = store = None

DAGENHAM = "https://schoolhire.co.uk/Dagenham/dagenham-park-leisure-centre/basketball-court/17294"


@unittest.skipIf(court_app is None, "flask not installed")
class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = mock.patch.object(store, "PATH", Path(self.tmp.name) / "courts.json")
        self.path.start()
        court_app.config["fixture"] = ROOT / "get.json"
        court_app._cache.clear()
        self.client = court_app.app.test_client()

    def tearDown(self):
        self.path.stop()
        self.tmp.cleanup()

    def test_default_filters(self):
        data = self.client.get("/api/slots").get_json()
        self.assertTrue(data["demo"])
        self.assertEqual(data["start"], "2026-09-28")
        self.assertEqual(data["groups"], [{"id": "east-london", "name": "East London"}])
        self.assertEqual(len(data["courts"]), 7)  # the example group, until you change it
        self.assertEqual([(w["date"], w["start"], w["end"]) for w in data["windows"]], [
            ("2026-09-29", "17:00", "19:00"), ("2026-10-03", "09:00", "12:00"),
            ("2026-10-03", "14:00", "18:00"), ("2026-10-04", "09:00", "11:00"),
            ("2026-10-04", "13:00", "18:00")])

    def test_filters_and_hidden_courts(self):
        data = self.client.get("/api/slots?weekdays=5&min_free=100").get_json()
        self.assertEqual([(w["start"], w["end"]) for w in data["windows"]],
                         [("09:00", "10:30"), ("14:00", "18:00")])
        data = self.client.get("/api/slots?hide=" + DAGENHAM).get_json()
        self.assertEqual(data["windows"], [])

    def test_groups(self):
        groups = self.client.post("/api/groups", json={"name": "Tuesday crew"}).get_json()
        crew = groups[-1]["id"]
        self.assertEqual(self.client.post("/api/groups", json={"name": "tuesday CREW"}).status_code, 400)
        data = self.client.get(f"/api/slots?group={crew}").get_json()
        self.assertEqual((data["group"], data["courts"], data["windows"]), (crew, [], []))

        # a deleted group falls back to every court
        self.client.delete(f"/api/groups/{crew}")
        data = self.client.get(f"/api/slots?group={crew}").get_json()
        self.assertEqual((data["group"], len(data["courts"])), ("", 7))

    def test_add_edit_remove_court(self):
        page = (ROOT / "tests" / "court_page.html").read_text(encoding="utf-8")
        link = ("https://schoolhire.co.uk/london-brent/kingsbury-high-school-upper/"
                "basketball-court/4532?date=31%2F10%2F2026")
        with mock.patch.object(store, "fetch_page", return_value=page) as fetch:
            r = self.client.post("/api/groups/east-london/courts", json={"url": link})
        self.assertEqual(r.status_code, 200, r.get_json())
        url = "https://schoolhire.co.uk/london-brent/kingsbury-high-school-upper/basketball-court/4532"
        fetch.assert_called_once_with(url)
        added = r.get_json()["added"]
        self.assertEqual((added["name"], added["price"], added["court"]),
                         ("Kingsbury High School (Upper)", 31.5, "half"))
        self.assertEqual(len(r.get_json()["groups"][0]["courts"]), 8)

        # the same court twice, or a link that isn't a court
        with mock.patch.object(store, "fetch_page", return_value=page):
            self.assertEqual(self.client.post("/api/groups/east-london/courts",
                                              json={"url": link}).status_code, 400)
        r = self.client.post("/api/groups/east-london/courts", json={"url": "https://example.com/x"})
        self.assertIn("schoolhire.co.uk", r.get_json()["error"])

        groups = self.client.patch("/api/groups/east-london/courts",
                                   json={"url": url, "price": "30", "court": "full"}).get_json()
        court = next(c for c in groups[0]["courts"] if c["url"] == url)
        self.assertEqual((court["price"], court["court"]), (30.0, "full"))
        self.assertEqual(self.client.patch("/api/groups/east-london/courts",
                                           json={"url": url, "price": "lots"}).status_code, 400)

        groups = self.client.delete(f"/api/groups/east-london/courts?url={url}").get_json()
        self.assertEqual(len(groups[0]["courts"]), 7)

    def test_drive_guesses(self):
        groups = self.client.put("/api/groups/east-london", json={"from": "Pell St"}).get_json()
        self.assertEqual((groups[0]["name"], groups[0]["from"]), ("East London", "Pell St"))
        self.client.patch("/api/groups/east-london/courts",
                          json={"url": DAGENHAM, "drive_min": "37"})
        self.assertEqual(self.client.patch("/api/groups/east-london/courts",
                                           json={"url": DAGENHAM, "drive_min": "far"}).status_code, 400)
        data = self.client.get("/api/slots?sort=drive").get_json()
        dagenham = next(c for c in data["courts"] if c["url"] == DAGENHAM)
        self.assertEqual(dagenham["drive"], [{"from": "Pell St", "min": 37}])
        self.assertEqual(data["windows"][0]["drive"], [{"from": "Pell St", "min": 37}])
        self.assertEqual(len(data["windows"]), 5)
        self.assertEqual(data["windows"][0]["directions"][0]["from"], "Pell St")
        self.assertIn("destination=RM10+9QH", data["windows"][0]["directions"][0]["url"])

    def test_site_down_when_adding(self):
        with mock.patch.object(store, "fetch_page", side_effect=OSError("timed out")):
            r = self.client.post("/api/groups/east-london/courts", json={
                "url": "https://schoolhire.co.uk/a/b/basketball-court/1"})
        self.assertEqual(r.status_code, 502)
        self.assertIn("timed out", r.get_json()["error"])

    def test_court_by_court_loading(self):
        # nothing loaded yet: answers at once, every court pending, no slots
        data = self.client.get("/api/slots?fetch=0").get_json()
        self.assertEqual(len(data["courts"]), 7)
        self.assertTrue(all(c["pending"] for c in data["courts"]))
        self.assertEqual(data["windows"], [])
        self.assertEqual(court_app._cache, {})

        # fetch one court: its slots appear, the others are still pending
        r = self.client.post("/api/fetch", json={"url": DAGENHAM, "days": 14})
        self.assertEqual(r.get_json(), {"url": DAGENHAM, "error": None, "slots": 19})
        data = self.client.get("/api/slots?fetch=0").get_json()
        self.assertEqual([c["url"] for c in data["courts"] if not c["pending"]], [DAGENHAM])
        self.assertEqual(len(data["windows"]), 5)

        # a different date range makes it pending again, without showing the old range
        data = self.client.get("/api/slots?fetch=0&days=7").get_json()
        self.assertTrue(all(c["pending"] for c in data["courts"]))
        self.assertEqual(data["windows"], [])

        # only courts in your groups can be fetched
        r = self.client.post("/api/fetch", json={"url": "https://schoolhire.co.uk/a/b/c/1"})
        self.assertEqual(r.status_code, 404)

    def test_fetch_reuses_cache_unless_refreshed(self):
        calls = []
        real = court_app.fetch_one
        def counting(court, start, days):
            calls.append(court["url"])
            return real(court, start, days)
        with mock.patch.object(court_app, "fetch_one", counting):
            for _ in range(2):
                self.client.post("/api/fetch", json={"url": DAGENHAM})
            self.assertEqual(len(calls), 1)
            # a refresh straight after a fetch (double click) reuses it ...
            self.client.post("/api/fetch", json={"url": DAGENHAM, "refresh": True})
            self.assertEqual(len(calls), 1)
            # ... but a refresh later fetches again
            court_app._cache[DAGENHAM]["at"] -= court_app.REFETCH_GAP + 1
            self.client.post("/api/fetch", json={"url": DAGENHAM, "refresh": True})
            self.assertEqual(len(calls), 2)

    def test_failed_court_shows_its_error_and_is_retried_later(self):
        calls = []
        def failing(court, start, days):
            calls.append(1)
            return {"key": (start, days), "at": court_app.time.time(), "slots": [],
                    "error": "timed out"}
        with mock.patch.object(court_app, "fetch_one", failing):
            self.client.post("/api/fetch", json={"url": DAGENHAM})
            data = self.client.get("/api/slots?fetch=0").get_json()
            dagenham = next(c for c in data["courts"] if c["url"] == DAGENHAM)
            self.assertEqual((dagenham["pending"], dagenham["error"]), (False, "timed out"))
            self.client.post("/api/fetch", json={"url": DAGENHAM})
            self.assertEqual(len(calls), 1)  # not straight away again
            court_app._cache[DAGENHAM]["at"] -= court_app.ERROR_RETRY + 1
            self.assertTrue(next(c for c in self.client.get("/api/slots?fetch=0").get_json()["courts"]
                                 if c["url"] == DAGENHAM)["pending"])

    def test_search_demo_marks_courts_you_have(self):
        data = self.client.get("/api/search?place=NW9").get_json()
        self.assertEqual((data["total"], len(data["results"])), (52, 52))
        self.assertEqual(data["results"][0]["in_groups"], [])
        rick = "https://schoolhire.co.uk/rickmansworth/rickmansworth-school/basketball-court/14655"
        self.client.put("/api/groups/east-london", json={"name": "East London"})
        data = store.load()
        data["groups"][0]["courts"].append({"name": "Rickmansworth School", "url": rick})
        store.save(data)
        found = self.client.get("/api/search?place=NW9").get_json()["results"]
        self.assertEqual(next(r for r in found if r["url"] == rick)["in_groups"], ["East London"])

    def test_grid_has_every_slot_cut_to_the_filters(self):
        self.assertNotIn("grid", self.client.get("/api/slots").get_json())
        data = self.client.get("/api/slots?view=grid&weekdays=1&after=17:30").get_json()
        self.assertEqual([(g["date"], g["start"], g["end"], g["free"]) for g in data["grid"]], [
            ("2026-09-29", "17:30", "18:00", 100), ("2026-09-29", "18:00", "19:00", 50),
            ("2026-09-29", "19:00", "20:30", 25), ("2026-09-29", "20:30", "22:00", 0)])
        self.assertEqual({g["url"] for g in data["grid"]}, {DAGENHAM})
        hidden = self.client.get("/api/slots?view=grid&hide=" + DAGENHAM).get_json()
        self.assertEqual(hidden["grid"], [])

    def test_bad_time(self):
        self.assertEqual(self.client.get("/api/slots?after=abc").status_code, 400)

    def test_page(self):
        self.assertIn(b"Court Finder", self.client.get("/").data)


if __name__ == "__main__":
    unittest.main()
