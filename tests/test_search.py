import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import search  # noqa: E402

PAGE = (ROOT / "tests" / "search_results.html").read_text(encoding="utf-8")
NW9 = (51.583103799999996, -0.2534766)  # where the saved search was made


class ParseTest(unittest.TestCase):
    def test_every_result_nearest_first(self):
        results = search.parse_results(PAGE, NW9)
        self.assertEqual(len(results), 52)  # 20 cards on the page, 52 in the markers
        self.assertEqual(len({r["id"] for r in results}), 52)
        miles = [r["miles"] for r in results]
        self.assertEqual(miles, sorted(miles))
        self.assertLessEqual(miles[-1], 10)

    def test_card_details(self):
        upper = next(r for r in search.parse_results(PAGE, NW9) if r["id"] == 4532)
        self.assertEqual(upper, {
            "id": 4532, "url": "https://schoolhire.co.uk/london-brent/kingsbury-high-school-upper/"
                               "basketball-court/4532",
            "venue": "Kingsbury High School (Upper)", "facility": "Sports Hall",
            "address": "Princes Avenue, Kingsbury, Brent, NW9 9JR", "postcode": "NW9 9JR",
            "price": 31.5, "price_from": True, "lat": 51.5897316, "lng": -0.2747271, "miles": 1.0})

    def test_results_past_the_first_page_get_a_court_link(self):
        rick = next(r for r in search.parse_results(PAGE, NW9) if r["id"] == 14655)
        self.assertEqual(rick["url"],
                         "https://schoolhire.co.uk/rickmansworth/rickmansworth-school/basketball-court/14655")
        self.assertEqual((rick["venue"], rick["price"]), ("Rickmansworth School", None))

    def test_names_are_unescaped(self):
        names = {r["venue"] for r in search.parse_results(PAGE, NW9)}
        self.assertIn("St. Michael's Catholic Grammar School", names)

    def test_centre_of_a_saved_search(self):
        self.assertEqual(search.center_from_page(PAGE), NW9)


class Response:
    def __init__(self, status, body=None, text=""):
        self.status_code, self.body, self.text = status, body, text
        self.ok = status < 400

    def json(self):
        return self.body

    def raise_for_status(self):
        if not self.ok:
            raise OSError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, post_status=200):
        self.calls, self.cookies, self.post_status = [], {"XSRF-TOKEN": "abc%3D"}, post_status

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, params, headers))
        if url.startswith(search.POSTCODES_API):
            known = url.endswith("/NW94GD") or url.endswith("/outcodes/NW9")
            return Response(200 if known else 404,
                            {"result": {"latitude": NW9[0], "longitude": NW9[1]}} if known else {})
        return Response(200, text=PAGE)

    def post(self, url, files=None, headers=None, timeout=None):
        self.calls.append(("POST", url, files, headers))
        return Response(self.post_status, text=PAGE if self.post_status == 200 else "oops")


class FindTest(unittest.TestCase):
    def test_find_courts(self):
        session = FakeSession()
        found = search.find_courts("nw9 4gd", 10, session=session, today=dt.date(2026, 10, 31))
        self.assertEqual((found["place"], found["total"], len(found["results"])), ("NW9 4GD", 52, 52))
        _, url, fields, headers = next(c for c in session.calls if c[0] == "POST")
        self.assertEqual(url, "https://schoolhire.co.uk/all-facilities")
        self.assertEqual({k: v[1] for k, v in fields.items()}, {
            "lat": str(NW9[0]), "lng": str(NW9[1]), "categories": "Basketball Courts",
            "area": "London NW9 4GD", "date": "31/10/2026", "multi_venue_id": "",
            "distance": "10", "min_price": "0", "max_price": "10000", "update_center": "true"})
        self.assertEqual(headers["X-XSRF-TOKEN"], "abc=")

    def test_falls_back_to_get(self):
        session = FakeSession(post_status=422)
        found = search.find_courts("NW9", 5, session=session)
        self.assertEqual(session.calls[-1][2]["distance"], "5")  # the GET with the same fields
        # only courts within the distance asked for
        self.assertTrue(found["results"])
        self.assertTrue(all(r["miles"] <= 5.5 for r in found["results"]))

    def test_bad_input(self):
        for place in ("", "hello", "12345"):
            with self.assertRaises(search.SearchError, msg=place):
                search.find_courts(place, session=FakeSession())
        with self.assertRaisesRegex(search.SearchError, "couldn't find"):
            search.find_courts("E1 6AN", session=FakeSession())
        with self.assertRaisesRegex(search.SearchError, "distance"):
            search.find_courts("NW9", 7, session=FakeSession())


if __name__ == "__main__":
    unittest.main()
