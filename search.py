"""Find basketball courts on schoolhire.co.uk near a postcode.

This is the search behind schoolhire.co.uk/all-facilities. The site posts the
search centre and a few filters as form fields:

    POST https://schoolhire.co.uk/all-facilities
        lat, lng, categories=Basketball Courts, area, date=31/10/2026,
        distance=10 (miles), min_price, max_price, multi_venue_id, update_center=true

and gets back an HTML fragment with a card for each of the first 20 results
(link, facility name, address, price) and a data-markers list with *every*
result (id, position, venue link and name). Both are read here, so one request
finds all the courts in range; the cards add the details where there is one.

The search centre comes from postcodes.io (free, no key): a full postcode
("NW9 4GD") or just its first half ("NW9").
"""

from __future__ import annotations

import datetime as dt
import html
import json
import math
import re
from urllib.parse import quote, unquote

BASE = "https://schoolhire.co.uk"
SEARCH_URL = f"{BASE}/all-facilities"
CATEGORY = "Basketball Courts"
FACILITY_TYPE = "basketball-court"  # in court links: /<area>/<venue>/basketball-court/<id>
POSTCODES_API = "https://api.postcodes.io"
POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.I)
OUTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?$", re.I)
DISTANCES = (3, 5, 10, 15, 20)  # miles, as on the site


class SearchError(ValueError):
    """Something the person can fix, e.g. a postcode that doesn't exist."""


def miles_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line distance in miles between two (lat, lng) points."""
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


# --------------------------------------------------------------------------- parsing

def parse_cards(page: str) -> dict[int, dict]:
    """facility id -> details from the result cards (only the first page has them)."""
    cards = {}
    for block in page.split("<div class='room' data-controller='room'")[1:]:
        fid = re.search(r"id='facility_(\d+)'", block)
        link = re.search(r"<h4>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.S)
        if not fid or not link:
            continue
        address = re.search(r"class='address'>(.*?)</p>", block, re.S)
        price = re.search(r"class='price'>(.*?)</li>", block, re.S)
        price_text = text(price.group(1)) if price else ""
        amount = re.search(r"£\s*(\d+(?:\.\d+)?)", price_text)
        cards[int(fid.group(1))] = {
            "url": html.unescape(link.group(1)).split("?")[0],
            "facility": text(link.group(2)),
            "address": text(address.group(1)) if address else "",
            "price": float(amount.group(1)) if amount else None,
            "price_from": price_text.lower().startswith("from"),
        }
    return cards


def parse_markers(page: str) -> list[dict]:
    """Every result from the data-markers list: id, lat, lng, venue name and link."""
    m = re.search(r"data-markers='([^']*)'", page)
    if not m:
        return []
    out = []
    for marker in json.loads(html.unescape(m.group(1))):
        venue = re.search(r'href="([^"]+)"[^>]*>(.*?)</a>', marker.get("infowindow", ""), re.S)
        out.append({"id": int(marker["id"]), "lat": marker.get("lat"), "lng": marker.get("lng"),
                    "venue_path": venue.group(1) if venue else "",
                    "venue": html.unescape(text(venue.group(2))) if venue else ""})
    return out


def parse_results(page: str, center: tuple[float, float] | None = None) -> list[dict]:
    """All the courts in a search response, nearest first when the centre is known."""
    cards = parse_cards(page)
    results, seen = [], set()
    for m in parse_markers(page):
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        card = cards.get(m["id"], {})
        url = card.get("url") or f"{BASE}{m['venue_path']}/{FACILITY_TYPE}/{m['id']}"
        address = card.get("address", "")
        postcode = re.search(r"[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$", address)
        miles = (round(miles_between(center, (m["lat"], m["lng"])), 1)
                 if center and m["lat"] is not None else None)
        results.append({
            "id": m["id"], "url": url, "venue": m["venue"], "facility": card.get("facility", ""),
            "address": address, "postcode": postcode.group(0) if postcode else "",
            "price": card.get("price"), "price_from": card.get("price_from", False),
            "lat": m["lat"], "lng": m["lng"], "miles": miles,
        })
    if not results:  # no markers (the site changed?): fall back to the cards alone
        results = [{"id": fid, **c, "venue": "", "postcode": "", "lat": None, "lng": None,
                    "miles": None} for fid, c in cards.items()]
    results.sort(key=lambda r: (r["miles"] is None, r["miles"] or 0, r["venue"], r["id"]))
    return results


# --------------------------------------------------------------------------- fetching

def new_session():
    import requests
    from schoolhire import USER_AGENT
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def locate(place: str, session) -> dict:
    """{"lat", "lng", "area"} for a UK postcode ("NW9 4GD") or its first half ("NW9")."""
    place = " ".join(str(place or "").upper().split())
    if POSTCODE_RE.match(place):
        url = f"{POSTCODES_API}/postcodes/{quote(place.replace(' ', ''))}"
    elif OUTCODE_RE.match(place):
        url = f"{POSTCODES_API}/outcodes/{quote(place)}"
    else:
        raise SearchError("enter a postcode, e.g. NW9 4GD, or just its first half, e.g. NW9")
    r = session.get(url, timeout=30)
    result = r.json().get("result") if r.status_code == 200 else None
    if not result or result.get("latitude") is None:
        raise SearchError(f"couldn't find the postcode {place}")
    return {"lat": result["latitude"], "lng": result["longitude"], "area": f"London {place}"}


def search_fields(where: dict, miles: int, date: dt.date) -> dict:
    return {"lat": str(where["lat"]), "lng": str(where["lng"]), "categories": CATEGORY,
            "area": where["area"], "date": date.strftime("%d/%m/%Y"), "multi_venue_id": "",
            "distance": str(miles), "min_price": "0", "max_price": "10000",
            "update_center": "true"}


def fetch_results(where: dict, miles: int, date: dt.date, session) -> str:
    """The search response, posted the way the site's own search page does it."""
    fields = search_fields(where, miles, date)
    # opening the search page first gives the session the site's cookies
    session.get(SEARCH_URL, params={"categories": CATEGORY, "area": where["area"],
                                    "date": fields["date"]}, timeout=30)
    headers = {"Accept": "application/json, text/plain, */*", "Origin": BASE,
               "Referer": f"{SEARCH_URL}?categories={quote(CATEGORY)}&area={quote(where['area'])}"}
    token = session.cookies.get("XSRF-TOKEN")
    if token:
        headers["X-XSRF-TOKEN"] = unquote(token)
    # (None, value) makes requests send plain multipart form fields, like the browser
    r = session.post(SEARCH_URL, files={k: (None, v) for k, v in fields.items()},
                     headers=headers, timeout=30)
    if r.ok and "data-markers" in r.text:
        return r.text
    # the page-2 links on the site use the same fields as a GET, so try that too
    r = session.get(SEARCH_URL, params=fields, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text


def center_from_page(page: str) -> tuple[float, float] | None:
    """The search centre a saved response was made with (for demo mode)."""
    m = re.search(r"data-params='([^']*)'", page)
    if not m:
        return None
    params = json.loads(html.unescape(m.group(1)))
    return float(params["lat"]), float(params["lng"])


def find_courts(place: str, miles: int = 10, session=None,
                today: dt.date | None = None) -> dict:
    """Basketball courts within `miles` of a postcode, nearest first."""
    if miles not in DISTANCES:
        raise SearchError(f"the distance must be one of {', '.join(map(str, DISTANCES))} miles")
    session = session or new_session()
    where = locate(place, session)
    page = fetch_results(where, miles, today or dt.date.today(), session)
    center = (where["lat"], where["lng"])
    results = [r for r in parse_results(page, center)
               if r["miles"] is None or r["miles"] <= miles + 0.5]
    total = re.search(r"location-quantity'>\s*(\d+)\s+results?", page)
    return {"place": place.upper().strip(), "center": {"lat": center[0], "lng": center[1]},
            "miles": miles, "total": int(total.group(1)) if total else len(results),
            "results": results}
