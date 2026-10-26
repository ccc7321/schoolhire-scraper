"""Your groups of courts, and adding a court from its schoolhire.co.uk link.

Groups live in courts.json next to this file. It isn't in git, so everyone
keeps their own: the first time, it starts as a copy of courts.example.json.

    {"groups": [{"id": "east-london", "name": "East London", "from": "Pell St",
                 "courts": [{"name": ..., "url": ..., "price": 26.0,
                             "drive_min": 25, ...}]}]}

"from" is where the group usually sets off from, and each court's "drive_min"
is your guess at the drive from there, in minutes. Both are optional.

Paste a court's link (from your browser's address bar on schoolhire.co.uk)
and add_court() reads the school's name, postcode and hourly prices from that
page, so you don't have to type them.
"""

from __future__ import annotations

import html
import json
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
PATH = HERE / "courts.json"
EXAMPLE = HERE / "courts.example.json"
SITE = "schoolhire.co.uk"

_lock = threading.Lock()

# /<area>/<venue>/<facility type>/<facility id>, e.g.
# /london-brent/kingsbury-high-school-upper/basketball-court/4532
COURT_PATH_RE = re.compile(r"^/[\w%.-]+/[\w%.-]+/[\w%.-]+/(\d+)/?$")
POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}\b")
PRICE_RE = re.compile(r"\d+\.\d{2}")
MAX_DRIVE_MIN = 600


class CourtError(ValueError):
    """Something the person can fix, e.g. a link that isn't a schoolhire court."""


# --------------------------------------------------------------------------- storage

def load() -> dict:
    """Your groups, or the example ones the first time."""
    source = PATH if PATH.exists() else EXAMPLE
    data = json.loads(source.read_text(encoding="utf-8"))
    data.setdefault("groups", [])
    return data


def save(data: dict) -> None:
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(PATH)


def find_group(data: dict, group_id: str) -> dict:
    group = next((g for g in data["groups"] if g["id"] == group_id), None)
    if not group:
        raise CourtError("that group doesn't exist (any more)")
    return group


def courts_in(data: dict, group_id: str | None = None) -> list[dict]:
    """One group's courts, or every court once (a court can be in several groups).

    Each court comes back with "drive": [{"from": "Pell St", "min": 25}, ...],
    the drive guesses from the groups it's in (only the chosen group's, if any).
    """
    groups = [find_group(data, group_id)] if group_id else data["groups"]
    by_url: dict[str, dict] = {}
    for g in groups:
        for c in g["courts"]:
            court = by_url.setdefault(c["url"], {**c, "drive": []})
            if c.get("drive_min") is not None:
                guess = {"from": g.get("from") or g["name"], "min": c["drive_min"]}
                if guess not in court["drive"]:
                    court["drive"].append(guess)
    return list(by_url.values())


def change(fn):
    """Load, let fn edit the groups (it may raise CourtError), save, return them."""
    with _lock:
        data = load()
        result = fn(data)
        save(data)
        return result if result is not None else data


def clean_name(value, what: str = "group") -> str:
    name = " ".join(str(value or "").split())[:60]
    if not name:
        raise CourtError(f"the {what} needs a name")
    return name


def add_group(name: str) -> dict:
    def fn(data):
        n = clean_name(name)
        if any(g["name"].lower() == n.lower() for g in data["groups"]):
            raise CourtError(f"there's already a group called {n}")
        data["groups"].append({"id": uuid.uuid4().hex[:8], "name": n, "courts": []})
    return change(fn)


def rename_group(group_id: str, name: str) -> dict:
    return update_group(group_id, {"name": name})


def update_group(group_id: str, fields: dict) -> dict:
    """Change a group's name and/or "from", where it drives from (e.g. "Pell St")."""
    def fn(data):
        group = find_group(data, group_id)
        if "name" in fields:
            group["name"] = clean_name(fields["name"])
        if "from" in fields:
            group["from"] = " ".join(str(fields["from"] or "").split())[:60]
    return change(fn)


def delete_group(group_id: str) -> dict:
    def fn(data):
        find_group(data, group_id)
        data["groups"] = [g for g in data["groups"] if g["id"] != group_id]
    return change(fn)


def edit_court(group_id: str, url: str, fields: dict) -> dict:
    """Change a court's name, price (per hour), size ("half"/"full"), notes or
    drive_min (your guess at the drive from the group's "from", in minutes)."""
    def fn(data):
        court = next((c for c in find_group(data, group_id)["courts"] if c["url"] == url), None)
        if not court:
            raise CourtError("that court isn't in this group")
        if "name" in fields:
            court["name"] = clean_name(fields["name"], "court")
        if "price" in fields:
            try:
                court["price"] = None if fields["price"] in ("", None) else round(float(fields["price"]), 2)
            except (TypeError, ValueError):
                raise CourtError("the price must be a number, e.g. 26 or 31.50") from None
        if "court" in fields:
            court["court"] = "full" if str(fields["court"]).lower() == "full" else "half"
        if "notes" in fields:
            court["notes"] = " ".join(str(fields["notes"]).split())[:200]
        if "drive_min" in fields:
            court["drive_min"] = drive_minutes(fields["drive_min"])
    return change(fn)


def drive_minutes(value) -> int | None:
    """A drive guess in whole minutes, or None to clear it."""
    if value in ("", None):
        return None
    try:
        minutes = round(float(value))
    except (TypeError, ValueError, OverflowError):  # "lots", "nan", "inf"
        raise CourtError("the drive time must be a number of minutes, e.g. 25") from None
    if not 0 <= minutes <= MAX_DRIVE_MIN:
        raise CourtError(f"the drive time must be between 0 and {MAX_DRIVE_MIN} minutes")
    return minutes


def remove_court(group_id: str, url: str) -> dict:
    def fn(data):
        group = find_group(data, group_id)
        group["courts"] = [c for c in group["courts"] if c["url"] != url]
    return change(fn)


# --------------------------------------------------------------------------- adding by link

def court_page(link: str) -> str:
    """The court's page address from whatever was pasted, without ?date=… and so on.

    "https://schoolhire.co.uk/london-brent/kingsbury-high-school-upper/basketball-court/4532?date=31%2F10%2F2026"
    -> "https://schoolhire.co.uk/london-brent/kingsbury-high-school-upper/basketball-court/4532"
    """
    link = str(link or "").strip()
    if not re.match(r"^https?://", link):
        link = "https://" + link
    parts = urlsplit(link)
    host = parts.hostname or ""
    if host not in (SITE, "www." + SITE):
        raise CourtError("paste a link to a court on schoolhire.co.uk")
    if not COURT_PATH_RE.match(parts.path):
        raise CourtError("that link isn't a court page; open the court on schoolhire.co.uk "
                         "and copy the address, e.g. …/basketball-court/4532")
    return f"https://{SITE}{parts.path.rstrip('/')}"


def page_text(page_html: str) -> str:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page_html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def headings(page_html: str) -> list[str]:
    found = re.findall(r"<h[12][^>]*>(.*?)</h[12]>", page_html, flags=re.S | re.I)
    return [h for h in (page_text(x) for x in found) if h]


def read_court_page(page_html: str, url: str) -> dict:
    """Name, postcode and prices from a schoolhire court page.

    The page has two headings: the facility ("Sports Hall") and the venue with
    its area ("Kingsbury High School (Upper) in Brent"). Prices come from the
    "Pricing Details" table, e.g. "Half Sports Hall 18 x 9 31.50 31.50".
    """
    heads = headings(page_html)
    venue = next((h for h in heads if " in " in h), heads[-1] if heads else "")
    name = re.sub(r"\s+in\s+[^()]+$", "", venue).strip() or url.rstrip("/").split("/")[-3]
    text = page_text(page_html)
    postcode = POSTCODE_RE.search(text)

    pricing = text.split("Pricing Details", 1)[1] if "Pricing Details" in text else ""
    pricing = pricing.split("Prices shown", 1)[0]
    # the first price after the row's label; sizes like "18 x 9" have no pence so are skipped
    half = re.search(r"(?:\bhalf\b|1/2).*?(\d+\.\d{2})", pricing, re.I)
    full = re.search(r"\bfull\b.*?(\d+\.\d{2})", pricing, re.I)
    first = PRICE_RE.search(pricing)
    # the half-hall price if there is one (most bookings), else the full hall, else any
    price = (half.group(1) if half else full.group(1) if full else first.group(0) if first else None)
    notes = []
    if half and full:
        notes.append(f"full hall £{float(full.group(1)):g}")
    if re.search(r"consecutive bookings? discount", text, re.I):
        notes.append("consecutive booking discount")
    return {"name": name, "postcode": postcode.group(0) if postcode else "", "url": url,
            "price": float(price) if price else None,
            "court": "full" if full and not half else "half", "notes": " · ".join(notes)}


def fetch_page(url: str, session=None) -> str:
    import requests  # only needed when adding a court
    session = session or requests.Session()
    from schoolhire import USER_AGENT
    r = session.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    if r.status_code == 404:
        raise CourtError("schoolhire.co.uk says that court page doesn't exist")
    r.raise_for_status()
    return r.text


def add_court(group_id: str, link: str, page_html: str | None = None) -> dict:
    """Add the court behind a schoolhire link to a group. Returns the new court.

    page_html is for tests; normally the page is fetched from schoolhire.co.uk.
    """
    url = court_page(link)
    with _lock:
        group = find_group(load(), group_id)
        if any(c["url"] == url for c in group["courts"]):
            raise CourtError(f"that court is already in {group['name']}")
    court = read_court_page(page_html if page_html is not None else fetch_page(url), url)

    def fn(data):
        group = find_group(data, group_id)
        if any(c["url"] == url for c in group["courts"]):  # added meanwhile
            raise CourtError(f"that court is already in {group['name']}")
        group["courts"].append(court)
        return court
    return change(fn)
