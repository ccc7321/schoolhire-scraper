import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import courts as store  # noqa: E402

PAGE = (ROOT / "tests" / "court_page.html").read_text(encoding="utf-8")
URL = "https://schoolhire.co.uk/london-brent/kingsbury-high-school-upper/basketball-court/4532"


class LinkTest(unittest.TestCase):
    def test_court_links(self):
        for link in (URL + "?date=31%2F10%2F2026", URL + "/", "schoolhire.co.uk" + URL[24:],
                     "https://www.schoolhire.co.uk" + URL[24:], "  " + URL + "  "):
            self.assertEqual(store.court_page(link), URL, link)

    def test_not_court_links(self):
        for link in ("", "hello", "https://example.com/a/b/c/1",
                     "https://schoolhire.co.uk/browse-facilities/basketball-court",
                     "https://schoolhire.co.uk.evil.com/a/b/c/1",
                     "https://schoolhire.co.uk/a/b/basketball-court/notanumber"):
            with self.assertRaises(store.CourtError, msg=link):
                store.court_page(link)


class PageTest(unittest.TestCase):
    def test_reads_name_postcode_and_prices(self):
        court = store.read_court_page(PAGE, URL)
        self.assertEqual(court, {
            "name": "Kingsbury High School (Upper)", "postcode": "NW9 9JR", "url": URL,
            "price": 31.5, "court": "half",
            "notes": "full hall £57.75 · consecutive booking discount"})

    def test_half_hall_written_as_a_fraction(self):
        page = PAGE.replace("Half Sports Hall</td><td>18 x 9",
                            "1/2 Sports Hall - 2 Badminton Courts</td><td>19 x 16")
        self.assertEqual(store.read_court_page(page, URL)["price"], 31.5)

    def test_full_hall_only(self):
        page = PAGE.replace("<tr><td>Half Sports Hall</td><td>18 x 9</td><td>31.50</td><td>31.50</td></tr>", "")
        court = store.read_court_page(page, URL)
        self.assertEqual((court["price"], court["court"]), (57.75, "full"))

    def test_no_prices(self):
        page = PAGE.split("<h3>Pricing Details</h3>")[0] + "</body></html>"
        court = store.read_court_page(page, URL)
        self.assertEqual((court["name"], court["price"]), ("Kingsbury High School (Upper)", None))


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(store, "PATH", Path(self.tmp.name) / "courts.json")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_starts_from_the_example_and_saves_your_own(self):
        self.assertFalse(store.PATH.exists())
        self.assertEqual([g["name"] for g in store.load()["groups"]], ["East London"])
        store.add_group("Tuesday crew")
        self.assertTrue(store.PATH.exists())
        self.assertEqual([g["name"] for g in json.loads(store.PATH.read_text("utf-8"))["groups"]],
                         ["East London", "Tuesday crew"])
        # the example file itself is never changed
        self.assertEqual(len(json.loads(store.EXAMPLE.read_text("utf-8"))["groups"]), 1)

    def test_a_court_in_two_groups_is_checked_once(self):
        data = store.add_group("Weekend")
        weekend = data["groups"][-1]["id"]
        store.add_court(weekend, URL, page_html=PAGE)
        store.add_court("east-london", URL, page_html=PAGE)
        urls = [c["url"] for c in store.courts_in(store.load())]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(len(store.courts_in(store.load(), weekend)), 1)

    def test_group_names(self):
        with self.assertRaises(store.CourtError):
            store.add_group("   ")
        with self.assertRaises(store.CourtError):
            store.rename_group("nope", "X")
        data = store.rename_group("east-london", "  East   side ")
        self.assertEqual(data["groups"][0]["name"], "East side")

    def test_drive_guesses(self):
        dagenham = "https://schoolhire.co.uk/Dagenham/dagenham-park-leisure-centre/basketball-court/17294"
        store.update_group("east-london", {"from": "  Pell   St "})
        store.edit_court("east-london", dagenham, {"drive_min": "37.4"})
        data = store.load()
        self.assertEqual(data["groups"][0]["from"], "Pell St")
        court = next(c for c in store.courts_in(data) if c["url"] == dagenham)
        self.assertEqual((court["drive_min"], court["drive"]), (37, [{"from": "Pell St", "min": 37}]))
        # courts without a guess have none
        self.assertEqual(store.courts_in(data)[0]["drive"], [])

        # the same court in another group, driving from somewhere else
        weekend = store.add_group("Weekend")["groups"][-1]["id"]
        data = store.load()
        data["groups"][-1]["courts"].append({"name": "D", "url": dagenham, "drive_min": 55})
        store.save(data)
        both = next(c for c in store.courts_in(store.load()) if c["url"] == dagenham)
        # no "from" set: the group's name stands in for it
        self.assertEqual(both["drive"], [{"from": "Pell St", "min": 37}, {"from": "Weekend", "min": 55}])
        only = store.courts_in(store.load(), weekend)
        self.assertEqual([c["drive"] for c in only], [[{"from": "Weekend", "min": 55}]])

        # blank clears it; nonsense is refused
        store.edit_court("east-london", dagenham, {"drive_min": ""})
        self.assertIsNone(next(c for c in store.load()["groups"][0]["courts"]
                               if c["url"] == dagenham)["drive_min"])
        for bad in ("lots", "-5", "601", "inf", "nan"):
            with self.assertRaises(store.CourtError, msg=bad):
                store.edit_court("east-london", dagenham, {"drive_min": bad})

    def test_directions_links(self):
        atam = "https://schoolhire.co.uk/romford/atam/basketball-court/42220"
        court = lambda gid=None: next(c for c in store.courts_in(store.load(), gid) if c["url"] == atam)
        self.assertEqual(court()["directions"], [])  # no "from" yet
        store.update_group("east-london", {"from": "NW9 4GD, London"})
        self.assertEqual(court()["directions"], [{
            "from": "NW9 4GD, London",
            "url": "https://www.google.com/maps/dir/?api=1&origin=NW9+4GD%2C+London"
                   "&destination=RM6+4XX&travelmode=driving"}])

        # in two groups driving from different places: a link from each
        data = store.add_group("Weekend")
        weekend = data["groups"][-1]["id"]
        store.update_group(weekend, {"from": "E1 6AN"})
        data = store.load()
        data["groups"][-1]["courts"].append({"name": "ATAM Academy", "url": atam})  # no postcode
        store.save(data)
        self.assertEqual([d["from"] for d in court()["directions"]], ["NW9 4GD, London", "E1 6AN"])
        # without a postcode, the court's name is the destination
        self.assertIn("destination=ATAM+Academy", court(weekend)["directions"][0]["url"])


if __name__ == "__main__":
    unittest.main()
