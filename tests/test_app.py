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

    def test_site_down_when_adding(self):
        with mock.patch.object(store, "fetch_page", side_effect=OSError("timed out")):
            r = self.client.post("/api/groups/east-london/courts", json={
                "url": "https://schoolhire.co.uk/a/b/basketball-court/1"})
        self.assertEqual(r.status_code, 502)
        self.assertIn("timed out", r.get_json()["error"])

    def test_bad_time(self):
        self.assertEqual(self.client.get("/api/slots?after=abc").status_code, 400)

    def test_page(self):
        self.assertIn(b"Court Finder", self.client.get("/").data)


if __name__ == "__main__":
    unittest.main()
