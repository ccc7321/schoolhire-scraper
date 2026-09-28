import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import app as court_app
except ImportError:  # flask not installed
    court_app = None


@unittest.skipIf(court_app is None, "flask not installed")
class ApiTest(unittest.TestCase):
    def setUp(self):
        court_app.config["fixture"] = ROOT / "get.json"
        court_app._cache.clear()
        self.client = court_app.app.test_client()

    def test_default_filters(self):
        data = self.client.get("/api/slots").get_json()
        self.assertTrue(data["demo"])
        self.assertEqual(data["start"], "2026-09-28")
        self.assertEqual(len(data["courts"]), 7)
        self.assertEqual([(w["date"], w["start"], w["end"]) for w in data["windows"]], [
            ("2026-09-29", "17:00", "19:00"), ("2026-10-03", "09:00", "12:00"),
            ("2026-10-03", "14:00", "18:00"), ("2026-10-04", "09:00", "11:00"),
            ("2026-10-04", "13:00", "18:00")])

    def test_filters_and_hidden_courts(self):
        data = self.client.get("/api/slots?weekdays=5&min_free=100").get_json()
        self.assertEqual([(w["start"], w["end"]) for w in data["windows"]],
                         [("09:00", "10:30"), ("14:00", "18:00")])
        data = self.client.get("/api/slots?hide=Dagenham Park Leisure Centre").get_json()
        self.assertEqual(data["windows"], [])

    def test_bad_time(self):
        self.assertEqual(self.client.get("/api/slots?after=abc").status_code, 400)

    def test_page(self):
        self.assertIn(b"Court Finder", self.client.get("/").data)


if __name__ == "__main__":
    unittest.main()
